"""Inventory installed distributions without importing their executable code."""

import base64
import csv
import importlib.metadata
import json
import re
from pathlib import Path
from pathlib import PurePosixPath

from build_config import BuildConfigError
from build_records import fileHash
from build_records import objectHash
from build_records import rejectLinks


PYTHON_FILE = re.compile(r'python(?:w|\d+(?:_d)?)?\.(?:exe|dll)', re.IGNORECASE)
WINDOWS_ENVIRONMENT = {
  'implementation_name': 'cpython', 'implementation_version': '3.12.10',
  'os_name': 'nt', 'platform_machine': 'AMD64', 'platform_python_implementation': 'CPython',
  'platform_release': '10', 'platform_system': 'Windows', 'platform_version': '10',
  'python_full_version': '3.12.10', 'python_version': '3.12', 'sys_platform': 'win32',
}


def normalizedName(value: str) -> str:
  return re.sub(r'[-_.]+', '-', value).lower()


def readConstraints(path: Path) -> dict[str, str]:
  from packaging.requirements import Requirement

  result = {}
  for text in path.read_text(encoding='utf-8-sig').splitlines():
    if not text.strip() or text.lstrip().startswith('#'):
      continue
    requirement = Requirement(text)
    specifiers = list(requirement.specifier)
    if (requirement.url or requirement.marker or requirement.extras or len(specifiers) != 1
        or specifiers[0].operator != '==' or '*' in specifiers[0].version):
      raise BuildConfigError('Modular constraints must pin exact versions: ' + text)
    name = normalizedName(requirement.name)
    if name in result:
      raise BuildConfigError('Duplicate modular constraint: ' + name)
    result[name] = specifiers[0].version
  return result


def recordPath(value: str) -> str | None:
  normalized = value.replace('\\', '/')
  parts = normalized.split('/')
  if normalized.startswith('../'):
    # Installed console entry points belong to the preparation environment.
    return None
  if (not normalized or normalized.startswith('/') or ':' in normalized
      or any(part in ('', '.', '..') for part in parts)):
    raise BuildConfigError('Unsafe installed RECORD path: ' + value)
  return PurePosixPath(normalized).as_posix()


def importRoot(path: str) -> str | None:
  first = path.split('/')[0]
  if first.endswith(('.dist-info', '.egg-info', '.libs', '.data')):
    return None
  if '/' not in path:
    if not first.endswith(('.py', '.pyd')):
      return None
    first = first.split('.')[0]
  if not first.isidentifier():
    return None
  return first


def readDistributions(site: Path) -> dict[str, dict]:
  rejectLinks(site)
  distributions = {}
  for item in importlib.metadata.distributions(path=[str(site)]):
    name = normalizedName(item.metadata['Name'])
    location = Path(item._path)
    rejectLinks(location)
    if name in distributions or not location.resolve().is_relative_to(site.resolve()):
      raise BuildConfigError('Duplicate or outside distribution metadata: ' + name)
    record = location / 'RECORD'
    if not record.is_file():
      raise BuildConfigError('Selected environment needs installed wheel RECORD: ' + name)
    rows = {}
    omitted = []
    for row in csv.reader(record.read_text(encoding='utf-8').splitlines()):
      if len(row) != 3:
        raise BuildConfigError('Malformed installed RECORD: ' + name)
      path = recordPath(row[0])
      if path is None or '__pycache__' in PurePosixPath(path).parts or path.endswith('.pyc'):
        omitted.append(row[0])
        continue
      # Pip may retain a Windows wheel spelling and append its slash alias.
      previous = rows.get(path)
      if previous and previous[1:] != row[1:] and all(previous[1:]) and all(row[1:]):
        raise BuildConfigError('Contradictory installed RECORD aliases: ' + path)
      if not previous or row[1]:
        rows[path] = row
    distributions[name] = {
      'name': name, 'version': item.version, 'metadata_path': location.relative_to(site).as_posix(),
      'requires_dist': list(item.metadata.get_all('Requires-Dist') or []),
      'record_sha256': fileHash(record), 'records': rows,
      'import_roots': sorted({root for path in rows if (root := importRoot(path))}),
      'preparation_only_files': omitted,
    }
  return distributions


def readProvenance(paths: list[Path]) -> dict[str, dict]:
  result = {}
  for path in paths:
    document = json.loads(path.read_text(encoding='utf-8-sig'))
    if document.get('version') != '1' or not isinstance(document.get('install'), list):
      raise BuildConfigError('Expected a pip installation report: ' + str(path))
    for item in document['install']:
      metadata = item['metadata']
      name = normalizedName(metadata['name'])
      download = item.get('download_info', {})
      digest = download.get('archive_info', {}).get('hashes', {}).get('sha256')
      if not re.fullmatch('[0-9a-f]{64}', digest or '') or not download.get('url'):
        raise BuildConfigError('Download source has no SHA256: ' + name)
      value = {'version': metadata['version'], 'url': download['url'], 'sha256': digest,
               'report_sha256': fileHash(path)}
      if name in result and result[name] != value:
        # Reinstallation of the same archive is expected for shared namespace providers.
        comparable = ('version', 'url', 'sha256')
        if any(result[name][key] != value[key] for key in comparable):
          raise BuildConfigError('Distribution has conflicting download sources: ' + name)
      result[name] = value
  return result


def resolveOwnership(distributions: dict, seeds: dict[str, list[str]],
                     *, providers: dict[str, str], sourceRequirements: dict | None = None) -> dict:
  from packaging.requirements import Requirement

  sourceRequirements = sourceRequirements or {}
  consumers, direct, graph, findings = {}, {}, {}, []
  for owner, names in seeds.items():
    for value in names:
      name = normalizedName(Requirement(value).name)
      if name in direct and direct[name] != owner:
        raise BuildConfigError('A seed distribution has two owners: ' + name)
      direct[name] = owner

  def closure(owner, initial, allowFindings=False):
    queue = [(text, None, allowFindings) for text in initial]
    expanded = set()
    while queue:
      text, parent, sourceOnly = queue.pop()
      requirement = Requirement(text)
      if requirement.marker and not requirement.marker.evaluate(dict(WINDOWS_ENVIRONMENT, extra='')):
        continue
      requested = normalizedName(requirement.name)
      name = requested
      if name not in distributions:
        name = providers.get(requested, name)
      if name not in distributions:
        raise BuildConfigError('Missing dependency in prepared runtime: ' + text)
      provider = providers.get(requested, name)
      if provider not in distributions:
        raise BuildConfigError('Declared namespace provider is missing: ' + provider)
      if name != provider and distributions[name]['version'] != distributions[provider]['version']:
        raise BuildConfigError('Alias metadata and actual namespace provider versions differ: ' + requested)
      providedVersion = distributions[provider]['version']
      if not requirement.specifier.contains(providedVersion, prereleases=True):
        if not sourceOnly:
          raise BuildConfigError('Prepared runtime violates dependency: ' + text)
        findings.append({'status': 'observed/unqualified', 'source': owner,
                         'requirement': text, 'selected_distribution': provider,
                         'selected_version': providedVersion,
                         'release_gate': 'Unresolved vendor compatibility declaration'})
      if provider != requested:
        findings.append({'status': 'explicit-provider', 'source': parent or owner,
                         'requirement': text, 'selected_distribution': provider,
                         'selected_version': providedVersion,
                         'alias_metadata_version': distributions.get(requested, {}).get('version')})
      if name != provider:
        queue.append((provider + '==' + providedVersion, parent, False))
      if parent is not None:
        graph.setdefault(parent, set()).add(name)
      consumers.setdefault(name, set()).add(owner)
      extras = tuple(sorted(requirement.extras))
      identity = (name, extras)
      if identity in expanded:
        continue
      expanded.add(identity)
      for dependency in distributions[name]['requires_dist']:
        child = Requirement(dependency)
        if child.marker and not any(child.marker.evaluate(dict(WINDOWS_ENVIRONMENT, extra=extra))
                                    for extra in ('', *extras)):
          continue
        child.marker = None
        queue.append((str(child), name, False))

  for owner, initial in seeds.items():
    closure(owner, initial)
    closure(owner, sourceRequirements.get(owner, []), allowFindings=True)
  owners = {}
  for name, requiredBy in consumers.items():
    owners[name] = ('core' if 'core' in requiredBy else direct.get(name)
                    or (next(iter(requiredBy)) if len(requiredBy) == 1 else 'core'))
    if owners[name] == 'core' and name in direct and direct[name] != 'core':
      raise BuildConfigError('Core depends on an optional runtime seed: ' + name)
  for alias, provider in providers.items():
    if alias in owners and provider in owners:
      owners[alias] = owners[provider]
  # A shared distribution can acquire an extra through a different consumer.
  # Keep the selected extra's light closure with its Core owner as well.
  changed = True
  while changed:
    changed = False
    for name, dependencies in graph.items():
      if owners[name] != 'core':
        continue
      for dependency in dependencies:
        if owners[dependency] != 'core':
          if dependency in direct and direct[dependency] != 'core':
            raise BuildConfigError('Core extra depends on an optional runtime seed: ' + dependency)
          owners[dependency] = 'core'
          changed = True
  roots = {}
  for name, owner in owners.items():
    for root in distributions[name]['import_roots']:
      if root in roots and roots[root] != owner:
        raise BuildConfigError('Top-level package split across module owners: ' + root)
      roots[root] = owner
  requires = {owner: set() for owner in seeds if owner != 'core'}
  for name, dependencies in graph.items():
    owner = owners[name]
    for dependency in dependencies:
      target = owners[dependency]
      if target == owner or target == 'core':
        continue
      if owner == 'core':
        raise BuildConfigError('Core depends on an optional module: ' + name)
      requires[owner].add(target)
  # Source-only packages such as the pinned Ultralytics checkout also declare edges.
  for owner, texts in sourceRequirements.items():
    for text in texts:
      requirement = Requirement(text)
      if requirement.marker and not requirement.marker.evaluate(dict(WINDOWS_ENVIRONMENT, extra='')):
        continue
      name = normalizedName(requirement.name)
      name = name if name in owners else providers.get(name, name)
      if name in owners and owners[name] not in (owner, 'core'):
        requires[owner].add(owners[name])
  return {'distribution_owners': dict(sorted(owners.items())),
          'import_owners': dict(sorted(roots.items())),
          'requires': {key: sorted(value) for key, value in requires.items()},
          'compatibility_findings': sorted(findings, key=objectHash)}


def verifyRecordHash(path: Path, row: list[str]) -> None:
  if row[2] and str(path.stat().st_size) != row[2]:
    raise BuildConfigError('Installed RECORD size differs from payload: ' + str(path))
  if not row[1]:
    return
  algorithm, separator, encoded = row[1].partition('=')
  if algorithm != 'sha256' or not separator:
    raise BuildConfigError('Unsupported installed RECORD digest: ' + str(path))
  actual = base64.urlsafe_b64encode(bytes.fromhex(fileHash(path))).decode('ascii').rstrip('=')
  if actual != encoded:
    raise BuildConfigError('Installed RECORD digest differs from payload: ' + str(path))


def inventoryPayload(site: Path, distributions: dict, ownership: dict,
                     *, namespaceProviders: dict[str, str], omittedPython: list[dict]) -> dict:
  omissions = {item['path']: item for item in omittedPython}
  files, skipped, folded = {}, [], {}
  for name, owner in ownership['distribution_owners'].items():
    item = distributions[name]
    replacement = next((provider for root, provider in namespaceProviders.items()
                        if root in item['import_roots'] and provider != name), None)
    for relative, row in distributions[name]['records'].items():
      path = site / relative
      rejectLinks(path)
      if not path.is_file():
        raise BuildConfigError('Installed RECORD payload is missing: ' + relative)
      if PYTHON_FILE.fullmatch(path.name):
        reviewed = omissions.get(relative)
        expected = (reviewed or {}).get('excluded_file', {})
        if not expected or fileHash(path) != expected.get('sha256'):
          raise BuildConfigError('Another Python runtime is not permitted: ' + relative)
        skipped.append({'path': relative, 'distribution': name, 'reason': 'qualified-python-copy'})
        continue
      root = importRoot(relative)
      metadata = item['metadata_path']
      provider = (replacement if replacement and not relative.startswith(metadata + '/')
                  else namespaceProviders.get(root))
      if provider and provider != name:
        if provider not in ownership['distribution_owners']:
          raise BuildConfigError('Namespace provider is absent: ' + provider)
        if ownership['distribution_owners'][provider] != owner:
          raise BuildConfigError('Namespace metadata and provider have different owners: ' + root)
        skipped.append({'path': relative, 'distribution': name, 'provider': provider,
                        'reason': 'explicit-shared-namespace-provider'})
        continue
      verifyRecordHash(path, row)
      if relative.casefold() in folded and folded[relative.casefold()] != relative:
        raise BuildConfigError('Windows payload path collision: ' + relative)
      folded[relative.casefold()] = relative
      value = {'owner': owner, 'size': path.stat().st_size, 'sha256': fileHash(path),
               'distributions': [name]}
      if relative in files:
        previous = files[relative]
        if any(previous[key] != value[key] for key in ('owner', 'size', 'sha256')):
          raise BuildConfigError('Conflicting file owners: ' + relative)
        previous['distributions'].append(name)
      else:
        files[relative] = value
  for root, provider in namespaceProviders.items():
    if provider in ownership['distribution_owners'] and not any(
        importRoot(path) == root and provider in record['distributions']
        for path, record in files.items()):
      raise BuildConfigError('Explicit namespace provider has no payload: ' + root)
  return {'files': dict(sorted(files.items())), 'excluded_files': skipped}


def buildDependencyLock(distributions: dict, provenance: dict, ownership: dict,
                        inventory: dict, *, inputs: dict) -> dict:
  locked = {}
  for name, owner in ownership['distribution_owners'].items():
    item = distributions[name]
    origin = provenance.get(name)
    if origin is None or origin['version'] != item['version']:
      raise BuildConfigError('No matching installation provenance: ' + name)
    locked[name] = {'version': item['version'], 'owner': owner,
                    'import_roots': item['import_roots'], 'requires_dist': item['requires_dist'],
                    'download': {key: origin[key] for key in ('url', 'sha256')}}
  return {'schema_version': 1, 'python': {'version': '3.12.10', 'abi': 'cp312',
                                        'platform': 'win_amd64'},
          'inputs': inputs, 'distributions': locked,
          'compatibility_findings': ownership['compatibility_findings'],
          'namespace_policy': 'One output owner per import root; explicit provider substitutions'}
