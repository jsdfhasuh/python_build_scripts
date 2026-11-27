"""Build protocol-4 candidate Core and offline modules without the legacy publisher."""

import argparse
import ast
import base64
import csv
import hashlib
import importlib.util
import json
import os
import pprint
import re
import runpy
import shutil
import sys
import time
import tomllib
import traceback
from urllib.request import urlopen
from pathlib import Path

from build_config import BuildConfigError
from build_config import addRuntimeBranding
from build_config import readJsonObject
from build_config import resolveResourcePath
from build_config import validateIcon
from build_records import fileHash
from build_records import gitState
from build_records import objectHash
from build_records import rejectLinks
from build_records import scanFiles
from scripts import verify_vision_train_modules as loader
from vision_train_modular_archive import compressPackage
from vision_train_modular_crt import loadRuntimeProfile
from vision_train_modular_crt import prepareRuntime
from vision_train_modular_crt import qualifyVendorCrt
from vision_train_modular_index import CORE_ADMISSION_LOCK
from vision_train_modular_index import CORE_UPGRADE_LAUNCHER
from vision_train_modular_index import INDEX_FILE
from vision_train_modular_index import writeModuleIndex
from vision_train_modular_receipts import selectSourceStaging
from vision_train_modular_reuse import readReuseSource
from vision_train_modular_reuse import reuseArchive
from vision_train_modular_reuse import validateReuseCore
from vision_train_module_inventory import buildDependencyLock
from vision_train_module_inventory import inventoryPayload
from vision_train_module_inventory import importRoot
from vision_train_module_inventory import normalizedName
from vision_train_module_inventory import readConstraints
from vision_train_module_inventory import readDistributions
from vision_train_module_inventory import readProvenance
from vision_train_module_inventory import resolveOwnership
from vision_train_module_inventory import verifyRecordHash


ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / 'ci/visionworkshop-modular.json'
OMIT_SOURCE_PARTS = {'.git', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache'}


def canonicalBytes(value: dict) -> bytes:
  return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def writeCanonical(path: Path, value: dict, *, encoder=canonicalBytes,
                   maximumBytes: int | None = None) -> None:
  data = encoder(value)
  if maximumBytes is not None and len(data) > maximumBytes:
    raise BuildConfigError('Serialized metadata exceeds the application limit: '
                           + path.name + ' (' + str(len(data)) + ' > ' + str(maximumBytes) + ')')
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(data)


def copyFile(source: Path, destination: Path) -> None:
  rejectLinks(source)
  rejectLinks(destination)
  if destination.exists():
    raise BuildConfigError('Duplicate packaged file: ' + str(destination))
  destination.parent.mkdir(parents=True, exist_ok=True)
  shutil.copy2(source, destination)


def copyTree(source: Path, destination: Path, *, excludeModels: bool = False) -> None:
  rejectLinks(source)
  if not source.is_dir():
    raise BuildConfigError('Missing source/resource directory: ' + str(source))
  for directory, folders, names in os.walk(source, followlinks=False):
    base = Path(directory)
    for name in folders + names:
      rejectLinks(base / name)
    folders[:] = [name for name in folders if name not in OMIT_SOURCE_PARTS
                  and not (excludeModels and base == source and name == 'models')]
    for name in names:
      if name.endswith(('.pyc', '.pyo')):
        continue
      path = base / name
      copyFile(path, destination / path.relative_to(source))


def loadProfile(path: Path) -> tuple[dict, dict]:
  profile = json.loads(path.read_text(encoding='utf-8'))
  if profile.get('schema_version') != 1:
    raise BuildConfigError('Unsupported modular builder profile')
  pins = readConstraints(ROOT / profile['constraints'])
  for name, version in profile['extra_pins'].items():
    if name in pins and pins[name] != version:
      raise BuildConfigError('Extra pin conflicts with production baseline: ' + name)
    pins[name] = version
  return profile, pins


def pinnedSeeds(profile: dict, pins: dict) -> dict:
  result = {}
  for owner, names in profile['seeds'].items():
    result[owner] = []
    for name in names:
      canonical = normalizedName(name)
      if canonical not in pins:
        raise BuildConfigError('Seed has no exact constraint: ' + name)
      result[owner].append(canonical + '==' + pins[canonical])
  return result


def dependencyRecipe(profile: dict) -> dict:
  keys = ('seeds', 'extra_pins', 'extra_archives', 'distribution_providers', 'namespace_providers')
  result = {key: profile[key] for key in keys}
  result['vendor'] = {name: item for name, item in profile['vendor'].items() if item['owner'] != 'core'}
  return result


def readVendor(source: Path, profile: dict) -> dict:
  result = {}
  for name, declaration in profile['vendor'].items():
    directory = source / declaration['path']
    rejectLinks(directory)
    state = gitState(directory)
    if state['commit'] != declaration['commit'] or state['dirty']:
      raise BuildConfigError('Vendor checkout differs from the reviewed source: ' + name)
    result[name] = dict(declaration)
  project = tomllib.loads((source / profile['vendor']['ultralytics']['path']
                          / 'pyproject.toml').read_text(encoding='utf-8'))['project']
  result['ultralytics']['requirements'] = project['dependencies']
  result['ultralytics']['pyproject_sha256'] = fileHash(source / 'ultralytics/pyproject.toml')
  return result


def prepareInputs(args) -> dict:
  profile, pins = loadProfile(args.profile)
  output = args.output.resolve()
  output.mkdir(parents=True, exist_ok=False)
  seeds = pinnedSeeds(profile, pins)
  requirements = sorted({item for values in seeds.values() for item in values})
  (output / 'requirements.txt').write_text('\n'.join(requirements) + '\n', encoding='utf-8')
  (output / 'constraints.txt').write_text(
    '\n'.join(name + '==' + version for name, version in sorted(pins.items())) + '\n',
    encoding='utf-8')
  result = {'profile_sha256': fileHash(args.profile), 'seeds': seeds,
            'requirements': str(output / 'requirements.txt'),
            'constraints': str(output / 'constraints.txt'),
            'namespace_providers': profile['namespace_providers'],
            'scope': 'Selected closures; the root application requirements are not installed wholesale'}
  writeCanonical(output / 'preparation.json', result)
  return result


def prepareAssets(args) -> dict:
  source = args.source_root.resolve()
  profile, _pins = loadProfile(args.profile)
  assets = args.assets_root.resolve()
  if (assets == source or assets.is_relative_to(source) or source.is_relative_to(assets)
      or assets.is_relative_to(ROOT)):
    raise BuildConfigError('Prepared resources need an isolated directory outside both checkouts')
  assets.mkdir(parents=True, exist_ok=False)
  copyTree(source / 'static/models', assets / 'static/models')
  sys.path.insert(0, str(source))
  try:
    patchcore = runpy.run_path(str(source / 'anomaly_func/pretrained_weights.py'))
    patchcore['prepare_pretrained_weights'](assets)
    simplification = runpy.run_path(str(source / 'scripts/prepare_image_simplification_weights.py'))
    simplified = assets / simplification['WEIGHT_RELATIVE_PATH']
    if simplified.exists():
      simplification['validate_weight_file'](str(simplified))
    else:
      simplification['prepare'](str(simplified), download=True)
    dino = runpy.run_path(str(source / 'anomaly_func/dinov2_resources.py'))
    destination = assets / 'static/models/dinov2-small' / dino['REVISION']
    if destination.exists():
      dino['verify_default'](destination)
    else:
      cache = dino['prepare_default']()
      copyTree(cache, destination)
      dino['verify_default'](destination)
    prepareCoreResources(assets, profile)
    result = {'files': fileRecords(assets), 'resource_root': str(assets),
              'core_resource_sources': profile['core_prepared_resources'],
              'preparation_sources': {name: fileHash(source / name) for name in (
                'anomaly_func/pretrained_weights.py', 'anomaly_func/dinov2_resources.py',
                'scripts/prepare_image_simplification_weights.py',
                'project__func/image_simplification/pretrained_weights.py')},
              'scope': 'Explicit online preparation; installed product does not download models'}
    writeCanonical(args.output, result)
    return result
  finally:
    sys.path.remove(str(source))


def prepareCrt(args) -> dict:
  profile, _pins = loadProfile(args.profile)
  contract = loadContract(args.source_root.resolve())
  declaration = loadRuntimeProfile(ROOT / profile['crt_profile'], contract)
  return prepareRuntime(args.output.resolve(), declaration)


def verifyPreparedCoreResource(path: Path, declaration: dict) -> None:
  rejectLinks(path)
  size = path.stat().st_size
  if size != declaration['size']:
    raise BuildConfigError('Prepared Core resource size differs from its fixed source: ' + str(path))
  gitDigest = hashlib.sha1(('blob ' + str(size) + '\0').encode('ascii'))
  digest = hashlib.sha256()
  with path.open('rb') as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
      gitDigest.update(chunk)
      digest.update(chunk)
  if (gitDigest.hexdigest() != declaration['git_blob_sha1']
      or digest.hexdigest() != declaration['sha256']):
    raise BuildConfigError('Prepared Core resource digest differs from its fixed source: ' + str(path))


def prepareCoreResources(assets: Path, profile: dict) -> None:
  for declaration in profile['core_prepared_resources']:
    relative = declaration['path']
    if (not relative.startswith('static/fonts/') or '\\' in relative or ':' in relative
        or any(part in ('', '.', '..') for part in relative.split('/'))):
      raise BuildConfigError('Prepared Core resource path is outside the declared font directory')
    if not re.fullmatch(
        r'https://raw\.githubusercontent\.com/notofonts/noto-cjk/[0-9a-f]{40}/.+',
        declaration['source_url']):
      raise BuildConfigError('Core font preparation requires an immutable reviewed upstream URL')
    target = assets / relative
    if target.exists():
      verifyPreparedCoreResource(target, declaration)
      continue
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.download')
    try:
      total = 0
      with urlopen(declaration['source_url'], timeout=90) as reader, temporary.open('xb') as writer:
        while chunk := reader.read(min(1024 * 1024, declaration['size'] - total + 1)):
          total += len(chunk)
          if total > declaration['size']:
            raise BuildConfigError('Core font download exceeds the reviewed source size')
          writer.write(chunk)
      verifyPreparedCoreResource(temporary, declaration)
      os.replace(temporary, target)
    finally:
      temporary.unlink(missing_ok=True)


def copyPreparedCoreResources(assets: Path, core: Path, profile: dict) -> None:
  for declaration in profile['core_prepared_resources']:
    source = assets / declaration['path']
    verifyPreparedCoreResource(source, declaration)
    copyFile(source, core / 'python' / declaration['path'])


def loadContract(source: Path):
  path = source / 'module_contract.py'
  if not path.is_file() or not (source / 'module_runtime.py').is_file():
    raise BuildConfigError('Application must provide the shared protocol-4 contract and manager')
  sys.path.insert(0, str(source))
  try:
    spec = importlib.util.spec_from_file_location('visionworkshop_application_module_contract', path)
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
  finally:
    sys.path.remove(str(source))
  if contract.PROTOCOL_VERSION != 4 or contract.MODULE_API != 1:
    raise BuildConfigError('Unsupported application module contract')
  return contract


def copyApplication(source: Path, core: Path, profile: dict) -> list[str]:
  python = core / 'python'
  python.mkdir(parents=True)
  for path in sorted(source.glob('*.py')):
    if path.name not in {'build.py', 'setup.py', 'test.py'}:
      copyFile(path, python / path.name)
  for name in profile['core_source_directories']:
    copyTree(source / name, python / name)
  for name in profile['core_resource_directories']:
    copyTree(source / name, python / name, excludeModels=name == 'static')
  for name in profile['core_resource_files']:
    copyFile(source / name, python / name)
  anylabeling = source / profile['vendor']['anylabeling']['path']
  copyTree(anylabeling / 'anylabeling', python / 'X-AnyLabeling/anylabeling')
  for name in ('LICENSE', 'README.md'):
    if (anylabeling / name).is_file():
      copyFile(anylabeling / name, python / 'X-AnyLabeling' / name)
  roots = {path.stem for path in python.glob('*.py')}
  roots.update(path.name for path in python.iterdir() if path.is_dir()
               and path.name.isidentifier() and any(path.rglob('*.py')))
  roots.add('anylabeling')
  return sorted(roots)


def copyInstalled(site: Path, inventory: dict, core: Path, modules: Path) -> None:
  for relative, record in inventory['files'].items():
    base = core if record['owner'] == 'core' else modules / record['owner'] / 'payload'
    copyFile(site / relative, base / 'site-packages' / relative)


def copyBranding(source: Path, core: Path, profile: dict) -> dict:
  profilePath = ROOT / profile['branding_profile']
  declaration = readJsonObject(profilePath)
  if (declaration.get('schema_version') != 1 or declaration.get('target') != 'emo-vision-train'
      or declaration.get('program_name') != 'VisionWorkshop'):
    raise BuildConfigError('The modular Core requires the existing VisionWorkshop branding profile')
  icon = resolveResourcePath(declaration['icon_path'], ROOT, str(source), 'Core icon')
  config = resolveResourcePath(declaration['runtime_branding_path'], ROOT, str(source), 'Core branding')
  resolved = {}
  addRuntimeBranding(resolved, config)
  runtime = resolved['runtime_branding']
  if validateIcon(icon) != runtime['window_icon_sha256']:
    raise BuildConfigError('Core EXE and window branding must use the same approved icon')
  copyFile(config, core / 'python/branding.json')
  copyFile(icon, core / 'python' / runtime['window_icon'])
  return {**runtime, 'icon_source': str(icon), 'profile': str(profilePath),
          'profile_sha256': fileHash(profilePath)}


def sourceVersion(path: Path) -> str:
  for node in ast.parse(path.read_text(encoding='utf-8')).body:
    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                                           and target.id == '__version__' for target in node.targets):
      value = ast.literal_eval(node.value)
      if isinstance(value, str) and re.fullmatch(r'[0-9A-Za-z.+_-]+', value):
        return value
  raise BuildConfigError('Cannot identify the pinned source package version: ' + str(path))


def copyUltralytics(source: Path, modules: Path, vendor: dict) -> dict:
  directory = source / vendor['path']
  root = modules / vendor['owner'] / 'payload'
  site = root / 'site-packages'
  package = site / 'ultralytics'
  copyTree(directory / 'ultralytics', package)
  version = sourceVersion(package / '__init__.py')
  project = tomllib.loads((directory / 'pyproject.toml').read_text(encoding='utf-8'))['project']
  metadata = site / ('ultralytics-' + version + '.dist-info')
  metadata.mkdir()
  lines = ['Metadata-Version: 2.3', 'Name: ' + project['name'], 'Version: ' + version,
           'Summary: ' + project['description'], 'Requires-Python: ' + project['requires-python']]
  lines.extend('Requires-Dist: ' + item for item in project['dependencies'])
  (metadata / 'METADATA').write_text('\n'.join(lines) + '\n', encoding='utf-8')
  (metadata / 'INSTALLER').write_text('VisionWorkshop source-tree inventory\n', encoding='utf-8')
  writeCanonical(metadata / 'direct_url.json', {
    'url': 'https://github.com/ultralytics/ultralytics',
    'vcs_info': {'vcs': 'git', 'commit_id': vendor['commit']}})
  with (metadata / 'RECORD').open('w', encoding='utf-8', newline='') as stream:
    writer = csv.writer(stream)
    files = [*package.rglob('*'), *metadata.iterdir()]
    for path in sorted(files):
      if path.is_file() and path.name != 'RECORD':
        digest = base64.urlsafe_b64encode(bytes.fromhex(fileHash(path))).decode().rstrip('=')
        writer.writerow([path.relative_to(site).as_posix(), 'sha256=' + digest, path.stat().st_size])
    writer.writerow([(metadata / 'RECORD').relative_to(site).as_posix(), '', ''])
  for name in ('pyproject.toml', 'LICENSE', 'README.md'):
    copyFile(directory / name, root / 'licenses/ultralytics' / name)
  writeCanonical(root / 'licenses/ultralytics/SOURCE.json', vendor)
  return {'version': version, 'owner': vendor['owner'], 'import_roots': ['ultralytics'],
          'requires_dist': project['dependencies'], 'source': dict(vendor, kind='git-tree'),
          'metadata': 'Generated faithfully from the pinned pyproject; not an upstream wheel'}


def copyResources(source: Path, modules: Path, profile: dict) -> dict:
  resources, owned = {}, set()
  for name, declaration in profile['resources'].items():
    mapping = {}
    for logical in declaration['paths']:
      path = source / logical
      rejectLinks(path)
      if not path.exists():
        raise BuildConfigError('Offline resource has not been prepared: ' + logical)
      relative = Path(logical).relative_to('static/models').as_posix()
      physical = 'resources/' + relative
      destination = modules / name / 'payload' / physical
      if path.is_dir():
        copyTree(path, destination)
        contents = [file for file in path.rglob('*') if file.is_file()]
      else:
        copyFile(path, destination)
        contents = [path]
      for file in contents:
        text = file.relative_to(source).as_posix()
        if text in owned:
          raise BuildConfigError('Model resource has two owners: ' + text)
        owned.add(text)
      mapping[logical] = physical
    resources[name] = mapping
  actual = {path.relative_to(source).as_posix() for path in (source / 'static/models').rglob('*')
            if path.is_file() and '__pycache__' not in path.parts}
  if actual != owned:
    raise BuildConfigError('Unassigned model resources: ' + ', '.join(sorted(actual - owned)))
  return resources


def fileRecords(root: Path) -> list[dict]:
  return [{'path': name, **record} for name, record in scanFiles(root).items()]


def nativeDirectories(records: list[dict], *, modulePayload: bool = False) -> list[str]:
  return sorted({Path(item['path']).parent.as_posix() for item in records
                 if item['path'].lower().endswith(('.dll', '.pyd'))
                 and not (modulePayload and Path(item['path']).parent.as_posix() == 'site-packages')})


def makeCatalog(profile: dict, ownership: dict, distributions: dict, resources: dict,
                vendor: dict) -> dict:
  catalog = {}
  for name in profile['labels']:
    members = {distribution: distributions[distribution]['version']
               for distribution, owner in ownership['distribution_owners'].items() if owner == name}
    roots = [root for root, owner in ownership['import_owners'].items() if owner == name]
    if name == vendor['owner']:
      members['ultralytics'] = vendor['version']
      roots.append('ultralytics')
    catalog[name] = {'kind': name.split('.')[0], 'label': profile['labels'][name],
                     'requires': ownership['requires'][name], 'distributions': dict(sorted(members.items())),
                     'import_roots': sorted(roots)}
  for name in resources:
    catalog[name] = {'kind': 'resource', 'label': profile['resources'][name]['label'],
                     'requires': [], 'distributions': {}, 'import_roots': []}
  return catalog


def validateAuxiliaryPayload(site: Path, distributions: dict, provenance: dict,
                             ownership: dict, declarations: list[dict]) -> dict:
  files = []
  for declaration in declarations:
    name = declaration['distribution']
    relative = declaration['path'].removeprefix('site-packages/')
    item, origin = distributions.get(name, {}), provenance.get(name, {})
    providers = [distribution for distribution in ownership['distribution_owners']
                 if relative in distributions[distribution]['records']]
    if (providers != [name] or item.get('version') != declaration['version']
        or origin.get('version') != declaration['version']
        or origin.get('sha256') != declaration['wheel_sha256']
        or ownership['distribution_owners'].get(name) != declaration['owner']
        or ownership['import_owners'].get(declaration['import_root']) != declaration['owner']
        or declaration['import_root'] not in item.get('import_roots', [])):
      raise BuildConfigError('Auxiliary site payload differs from its reviewed owner/wheel: ' + relative)
    path = site / relative
    rejectLinks(path)
    row = item['records'][relative]
    digest = base64.urlsafe_b64encode(bytes.fromhex(declaration['sha256'])).decode().rstrip('=')
    if row[1:] != ['sha256=' + digest, str(declaration['size'])]:
      raise BuildConfigError('Auxiliary site payload RECORD differs from its original bytes: ' + relative)
    verifyRecordHash(path, row)
    if path.stat().st_size != declaration['size'] or fileHash(path) != declaration['sha256']:
      raise BuildConfigError('Auxiliary site payload bytes changed: ' + relative)
    files.append({'declaration': declaration, 'wheel_provenance': origin,
                  'installed_record': row, 'record_sha256': item['record_sha256'],
                  'installed_path': str(path.resolve()), 'payload_unchanged': True})
  return {'status': 'PASS', 'files': files,
          'scope': 'Exact original auxiliary wheel files; no new import namespace or automatic .pth execution'}


def validateReadlineProvider(site: Path, distributions: dict, provenance: dict,
                             ownership: dict, declaration: dict) -> dict:
  name, namespace = declaration['distribution'], declaration['namespace']
  relative = declaration['path'].removeprefix('site-packages/')
  item, origin = distributions.get(name, {}), provenance.get(name, {})
  providers = [distribution for distribution in ownership['distribution_owners']
               if namespace in distributions[distribution]['import_roots']]
  if (providers != [name] or item.get('version') != declaration['version']
      or origin.get('version') != declaration['version']
      or origin.get('sha256') != declaration['wheel_sha256']
      or ownership['distribution_owners'].get(name) != declaration['owner']
      or any(ownership['import_owners'].get(root) != declaration['owner']
             for root in (namespace, name))):
    raise BuildConfigError('The Windows readline compatibility provider differs from its reviewed owner/wheel')
  variants = [path for path in item['records'] if (root := importRoot(path)) is not None
               and root.casefold() == namespace.casefold()]
  # Keep the original wheel shim, without a renamed module or replacement implementation.
  if variants != [relative]:
    raise BuildConfigError('Unexpected readline namespace payload in the Windows compatibility provider')
  path = site / relative
  rejectLinks(path)
  row = item['records'][relative]
  digest = base64.urlsafe_b64encode(bytes.fromhex(declaration['sha256'])).decode().rstrip('=')
  if row[1:] != ['sha256=' + digest, str(declaration['size'])]:
    raise BuildConfigError('Windows readline shim RECORD does not declare its reviewed original bytes')
  verifyRecordHash(path, row)
  if path.stat().st_size != declaration['size'] or fileHash(path) != declaration['sha256']:
    raise BuildConfigError('Windows readline shim differs from its reviewed original bytes')
  return {'declaration': declaration, 'wheel_provenance': origin,
          'installed_record': row, 'record_sha256': item['record_sha256'],
          'installed_path': str(path.resolve()), 'payload_unchanged': True}


def qualifyReadlineCompatibility(python: Path, info: dict, site: Path, distributions: dict,
                                 provenance: dict, ownership: dict, contract, reports: Path) -> dict:
  declaration = contract.READLINE_COMPATIBILITY
  record = {'status': 'FAIL', 'declaration': declaration}
  try:
    record.update(validateReadlineProvider(site, distributions, provenance, ownership, declaration))
    program = (
      'import importlib.util,json,sys; name=sys.argv[1]; spec=importlib.util.find_spec(name); '
      'print(json.dumps({"namespace":name,"version":sys.version.split()[0],'
      '"platform":sys.platform,"executable":sys.executable,"base_prefix":sys.base_prefix,'
      '"isolated":sys.flags.isolated,"no_site":sys.flags.no_site,'
      '"listed_in_stdlib_names":name in sys.stdlib_module_names,'
      '"builtin":name in sys.builtin_module_names,'
      '"spec":None if spec is None else {"origin":spec.origin,"loader":type(spec.loader).__name__}}))'
    )
    observed = json.loads(loader.runCommand(
      [str(python), '-I', '-S', '-B', '-c', program, declaration['namespace']], reports,
      'compiler-readline-absence', timeout=60, cwd=reports,
      env=loader.cleanBuildEnvironment(info, reports.parent)))
    record['compiler_observation'] = observed
    if (observed.get('namespace') != declaration['namespace']
        or observed.get('version') != '3.12.10' or observed.get('platform') != 'win32'
        or observed.get('isolated') != 1 or observed.get('no_site') != 1
        or observed.get('spec') is not None or observed.get('builtin') is not False
        or observed.get('listed_in_stdlib_names') is not True
        or Path(observed.get('executable', '')).resolve() != python.resolve()
        or Path(observed.get('base_prefix', '')).resolve() != Path(info['base_prefix']).resolve()):
      raise BuildConfigError('The fixed Windows compiler does not prove that native readline is absent')
    record.update(status='PASS', scope='One reviewed Windows-only compatibility shim; no general stdlib override')
    return record
  finally:
    loader.writeReport(reports / 'readline-compatibility.json', record)


def guardedBootloaderSpec(compiler: Path, source: Path, expected: str) -> str:
  rejectLinks(source)
  if not source.is_file() or source.name != 'runw.exe' or fileHash(source) != expected:
    raise BuildConfigError('The selected guarded runw.exe does not match its pinned SHA-256')
  staged = compiler / 'guarded-runw.exe'
  copyFile(source, staged)
  if fileHash(staged) != expected:
    raise BuildConfigError('Guarded bootloader changed while copying compiler input')
  return (
    'from PyInstaller import __version__ as pyinstaller_version\n'
    'if pyinstaller_version != "6.18.0":\n'
    '  raise RuntimeError("Guarded Core requires the pinned PyInstaller 6.18.0")\n'
    'class GuardedEXE(EXE):\n'
    '  def _bootloader_file(self, exe, extension=None):\n'
    '    standard = Path(super()._bootloader_file(exe, extension))\n'
    '    if standard.name != "runw.exe" or standard.parent.name != "Windows-64bit-intel":\n'
    '      raise RuntimeError("Guarded Core requires the x64 Windows release windowed bootloader")\n'
    '    return ' + repr(str(staged)) + '\n')


def buildFrozenCore(python: Path, info: dict, core: Path, metadata: dict, output: Path, reports: Path,
                    icon: Path, crtRoot: Path, crtProfile: dict, *,
                    admissionBootloader: Path | None = None, upgradeLauncher: Path | None = None) -> None:
  compiler = output / 'compiler-input'
  compiler.mkdir()
  admissionSha = metadata.get('admission_bootloader_sha256')
  if (admissionBootloader is not None) != ('admission_bootloader_sha256' in metadata):
    raise BuildConfigError('Guarded Core must bind its bootloader in the embedded metadata')
  guardSpec = (guardedBootloaderSpec(compiler, admissionBootloader, admissionSha)
               if admissionBootloader is not None else '')
  template = (ROOT / 'scripts/modular_product_launcher.py').read_text(encoding='utf-8')
  marker = "EMBEDDED_CORE_JSON = '__BUILD_CORE_JSON__'"
  if template.count(marker) != 1:
    raise BuildConfigError('The stdlib launcher template is not unique')
  entry = compiler / 'visionworkshop_core.py'
  embedded = (core / 'core.json').read_bytes()
  if guardSpec and json.loads(embedded).get('admission_bootloader_sha256') != admissionSha:
    raise BuildConfigError('Embedded Core admission identity differs from the selected bootloader')
  entry.write_text(template.replace(marker, 'EMBEDDED_CORE_JSON = '
                   + repr(embedded.decode('utf-8'))), encoding='utf-8')
  replacements = {name: str(crtRoot / 'dlls' / name)
                   for name in ('vcruntime140.dll', 'vcruntime140_1.dll')}
  native = [(str(Path(info['base_prefix']) / 'python3.dll'), '.')]
  native.extend((path, '.') for path in replacements.values())
  excluded = set(loader.STDLIB_EXCLUDED) | set(metadata['import_roots'])
  excluded.update(root for item in metadata['catalog'].values() for root in item['import_roots'])
  hidden = loader.collectStdlibModules(info)
  specification = compiler / 'VisionWorkshop.spec'
  specification.write_text(
    'import json\nfrom pathlib import Path\n' + guardSpec +
    'a = Analysis(' + repr([str(entry)]) + ', pathex=[], binaries=' + repr(native) + ', datas=[],\n'
    '  hiddenimports=' + pprint.pformat(hidden) + ',\n'
    '  hookspath=[], runtime_hooks=[], excludes=' + repr(sorted(excluded)) + ', noarchive=False)\n'
    'original_binaries = list(a.binaries)\n'
    'replacements = ' + repr(replacements) + '\n'
    'for name, source in replacements.items():\n'
    '  a.binaries = [row for row in a.binaries if row[0].lower() != name]\n'
    '  a.binaries.append((name, source, "BINARY"))\n'
    'Path(' + repr(str(reports / 'core-analysis.json')) + ').write_text(json.dumps({\n'
    '  "pure": list(a.pure), "binaries": list(a.binaries), "datas": list(a.datas),\n'
    '  "original_binaries": original_binaries, "reviewed_crt_replacements": replacements\n'
    '}), encoding="utf-8")\n'
    'pyz = PYZ(a.pure)\n'
    'exe = ' + ('GuardedEXE' if guardSpec else 'EXE') +
    '(pyz, a.scripts, [], exclude_binaries=True, name="VisionWorkshop",\n'
    '  debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False,\n'
    '  icon=' + repr(str(icon)) + ')\n'
    'coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="VisionWorkshop")\n',
    encoding='utf-8')
  environment = loader.cleanBuildEnvironment(info, output)
  loader.writeReport(reports / 'core-build-environment.json', {
    'path': environment['PATH'].split(os.pathsep), 'executable': str(python),
    'python_isolated_mode': True, 'embedded_core_sha256': hashlib.sha256(embedded).hexdigest(),
    'entry_sha256': fileHash(entry), 'hidden_imports': hidden})
  loader.runCommand([str(python), '-I', '-B', '-m', 'PyInstaller', '--clean', '--noconfirm',
                    '--distpath', str(output / 'compiler-output'),
                    '--workpath', str(output / 'compiler-work'), str(specification)],
                   reports, 'core-build', timeout=900, cwd=compiler, env=environment)
  if guardSpec:
    if fileHash(compiler / 'guarded-runw.exe') != admissionSha:
      raise BuildConfigError('Guarded bootloader changed during the build')
    loader.writeReport(reports / 'core-admission-bootloader.json', {'sha256': admissionSha,
      'pyinstaller': '6.18.0', 'lock_file': CORE_ADMISSION_LOCK})
  analysis = json.loads((reports / 'core-analysis.json').read_text(encoding='utf-8'))
  sourceSets = {}
  for key in ('original_binaries', 'binaries'):
    ordinary, reviewed = [], []
    for destination, source, kind in analysis[key]:
      expected = replacements.get(destination.lower())
      if expected and Path(source).resolve() == Path(expected).resolve():
        declared = crtProfile['files'][destination.lower()]
        if fileHash(Path(source)) != declared['sha256'] or Path(source).stat().st_size != declared['bytes']:
          raise BuildConfigError('A frozen official CRT input changed after preparation')
        reviewed.append({'destination': destination, 'path': str(Path(source).resolve()),
                         'owner': 'fixed-microsoft-redist', 'kind': kind,
                         'bytes': declared['bytes'], 'sha256': declared['sha256']})
      else:
        if expected and Path(source).resolve() != (Path(info['base_prefix']) / destination).resolve():
          raise BuildConfigError('PyInstaller initially selected an unreviewed VCRUNTIME source')
        ordinary.append((destination, source, kind))
    sourceSets[key] = reviewed + loader.validateBinarySources({'binaries': ordinary}, info,
      Path(os.environ['SystemRoot']).resolve())
  sources = sourceSets['binaries']
  for name, path in replacements.items():
    matches = [item for item in sources if item['destination'].lower() == name]
    if len(matches) != 1 or matches[0]['path'] != str(Path(path).resolve()):
      raise BuildConfigError('The frozen Core did not select its exact official VCRUNTIME input')
  compilerSite = Path(info['purelib']).resolve()
  leaked = [record['path'] for record in sources if Path(record['path']).is_relative_to(compilerSite)]
  loader.writeReport(reports / 'core-binary-sources.json', {
    'status': 'FAIL' if leaked else 'PASS', 'files': sources,
    'original_analysis_files': sourceSets['original_binaries'],
    'reviewed_crt_replacements': replacements, 'compiler_site_packages_leaks': leaked})
  if leaked:
    raise BuildConfigError('Third-party compiler test dependencies leaked into the frozen stdlib Core')
  optional = set(metadata['import_roots'])
  optional.update(root for item in metadata['catalog'].values() for root in item['import_roots'])
  if any(item[0].split('.')[0] in optional for item in analysis['pure']):
    raise BuildConfigError('Application or optional packages were frozen into the stdlib Core')
  built = output / 'compiler-output/VisionWorkshop'
  copyFile(built / 'VisionWorkshop.exe', core / 'VisionWorkshop.exe')
  copyTree(built / '_internal', core / '_internal')
  if guardSpec:
    admissionLock = core / CORE_ADMISSION_LOCK
    admissionLock.parent.mkdir()
    admissionLock.touch(exist_ok=False)
  launcherSha = metadata.get('core_update_launcher_sha256')
  if (upgradeLauncher is not None) != ('core_update_launcher_sha256' in metadata):
    raise BuildConfigError('Core must bind its stable upgrade launcher in the embedded metadata')
  if upgradeLauncher is not None:
    rejectLinks(upgradeLauncher)
    if not guardSpec or fileHash(upgradeLauncher) != launcherSha:
      raise BuildConfigError('Stable Core upgrade launcher does not match its admitted manifest')
    copyFile(upgradeLauncher, core / CORE_UPGRADE_LAUNCHER)
    if fileHash(core / CORE_UPGRADE_LAUNCHER) != launcherSha:
      raise BuildConfigError('Stable upgrade launcher changed during Core construction')
  for record in metadata['preload_dlls']:
    if fileHash(core / record['path']) != record['sha256']:
      raise BuildConfigError('Frozen Core ABI DLL differs from the selected interpreter')
  loader.inspectCoreArchive(python, core / 'VisionWorkshop.exe', reports, environment)


def buildCandidate(args) -> dict:
  started = time.monotonic()
  output = args.output.resolve()
  if output.exists():
    raise BuildConfigError('Use a new output directory for a modular candidate')
  output.mkdir(parents=True)
  reports = output / 'reports'
  reports.mkdir()
  result = {'status': 'FAIL', 'published': False, 'product_acceptance': 'NOT_RUN',
            'gpu_hardware': 'NOT_RUN', 'scope': 'Protocol-4 modular candidate; no Release publication'}
  try:
    if os.name != 'nt':
      raise BuildConfigError('Real modular product construction requires Windows')
    source = args.source_root.resolve()
    sourceState, packagerState = gitState(source), gitState(ROOT)
    if not sourceState['commit'] or sourceState['dirty'] or not sourceState['submodules_ready']:
      raise BuildConfigError('Application checkout must be clean, exact and include pinned submodules')
    if not packagerState['commit'] or packagerState['dirty']:
      raise BuildConfigError('Packager checkout must be clean and identify its exact commit')
    contract = loadContract(source)
    contract.stable_version(args.core_version)
    minimum, maximum = args.core_version, args.max_core_version
    if contract.stable_version(minimum) >= contract.stable_version(maximum):
      raise BuildConfigError('Core compatibility interval must be nonempty')
    profile, pins = loadProfile(args.profile)
    crtProfile = loadRuntimeProfile(ROOT / profile['crt_profile'], contract)
    vendor = readVendor(source, profile)
    buildInfo = loader.inspectPython(args.build_python.resolve(), reports, 'build-python')
    runtimeInfo = loader.inspectPython(args.runtime_python.resolve(), reports, 'runtime-python')
    if buildInfo['prefix'] == runtimeInfo['prefix']:
      raise BuildConfigError('Keep compiler and dependency preparation environments separate')
    loader.validateVersions(buildInfo, loader.BUILD_VERSIONS)
    # The complete candidate validates all selected versions and explicit providers below.
    # The B2 probe's one-ORT-distribution rule does not describe this preparation environment.
    site = Path(runtimeInfo['purelib'])
    selectedPython = Path(buildInfo['base_prefix']) / 'python312.dll'
    omitted = [loader.qualifyVendoredPython(site, Path(loader.TORCHVISION_PYTHON['path']),
                                           selectedPython, args.torch_install_report.resolve())]
    loader.writeReport(reports / 'interpreter-ownership.json', {'reviewed_omissions': omitted})
    distributions = readDistributions(site)
    provenance = readProvenance(args.install_report)
    seeds = pinnedSeeds(profile, pins)
    ownership = resolveOwnership(distributions, seeds, providers=profile['distribution_providers'],
                                  sourceRequirements={'feature.yolo': vendor['ultralytics']['requirements']})
    for name in ownership['distribution_owners']:
      if distributions[name]['version'] != pins.get(name):
        raise BuildConfigError('Dependency closure contains an unpinned or changed version: ' + name)
    for name, digest in profile['extra_archives'].items():
      if provenance.get(name, {}).get('sha256') != digest:
        raise BuildConfigError('Added dependency archive differs from its reviewed digest: ' + name)
    readline = qualifyReadlineCompatibility(args.build_python.resolve(), buildInfo, site,
      distributions, provenance, ownership, contract, reports)
    auxiliary = validateAuxiliaryPayload(site, distributions, provenance, ownership,
                                          contract.AUXILIARY_PAYLOAD_FILES)
    loader.writeReport(reports / 'auxiliary-payload-compatibility.json', auxiliary)
    inventory = inventoryPayload(site, distributions, ownership,
                                 namespaceProviders=profile['namespace_providers'], omittedPython=omitted)
    loader.writeReport(reports / 'installed-distributions.json', {'distributions': distributions,
                                                               'provenance': provenance})
    loader.writeReport(reports / 'ownership.json', ownership)
    loader.writeReport(reports / 'installed-file-ownership.json', inventory)
    core = output / 'layout/VisionWorkshop'
    modules = output / 'module-staging'
    applicationRoots = copyApplication(source, core, profile)
    copyPreparedCoreResources(args.assets_root.resolve(), core, profile)
    branding = copyBranding(source, core, profile)
    loader.writeReport(reports / 'core-branding-source.json', branding)
    copyInstalled(site, inventory, core, modules)
    sourcePackage = copyUltralytics(source, modules, vendor['ultralytics'])
    resources = copyResources(args.assets_root.resolve(), modules, profile)
    crtRoot = args.crt_root.resolve()
    crt = qualifyVendorCrt(site, distributions, provenance, ownership, crtRoot,
                           crtProfile, contract, reports)
    for name, destination in crtProfile['core_files'].items():
      if destination.startswith('native/'):
        copyFile(crtRoot / 'dlls' / name, core / destination)
    copyTree(crtRoot / 'licenses', core / 'native/msvc-licenses')
    loader.writeReport(reports / 'core-crt-source.json', {'profile': crtProfile,
      'profile_sha256': fileHash(ROOT / profile['crt_profile']), 'shared_compatibility': crt})
    lock = buildDependencyLock(distributions, provenance, ownership, inventory, inputs={
      'dependency_recipe_sha256': objectHash(dependencyRecipe(profile)),
      'constraints_sha256': fileHash(ROOT / profile['constraints']),
      'vendor_sources': {name: item for name, item in vendor.items() if item['owner'] != 'core'},
      'namespace_providers': profile['namespace_providers'],
      'distribution_providers': profile['distribution_providers'],
      'windows_stdlib_compatibility': contract.READLINE_COMPATIBILITY,
      'auxiliary_payload_files': contract.AUXILIARY_PAYLOAD_FILES,
      'msvcp_compatibility': contract.MSVCP140_COMPATIBILITY,
      'core_crt_profile_sha256': fileHash(ROOT / profile['crt_profile'])})
    lock['distributions']['ultralytics'] = sourcePackage
    writeCanonical(core / contract.LOCK_FILE, lock, encoder=contract.canonical_json,
                    maximumBytes=contract.MAX_METADATA)
    records = fileRecords(core)
    build = {'app_sha': sourceState['commit'], 'packager_sha': packagerState['commit'],
             'build_id': args.build_id}
    preloads = [{'path': crtProfile['core_files'][name], 'sha256': crtProfile['files'][name]['sha256']}
                 for name in crtProfile['preload_order']]
    metadata = {
      'protocol_version': contract.PROTOCOL_VERSION, 'module_api': contract.MODULE_API,
      'type': 'visionworkshop-core', 'version': args.core_version,
      'python': lock['python'], 'entrypoint': 'VisionWorkshop.exe', 'build': build,
      'dependency_lock_sha256': fileHash(core / contract.LOCK_FILE),
      'distributions': {name: distributions[name]['version'] for name, owner
                        in ownership['distribution_owners'].items() if owner == 'core'},
      'import_roots': sorted(set(applicationRoots) | {root for root, owner
                             in ownership['import_owners'].items() if owner == 'core'}),
      'catalog': makeCatalog(profile, ownership, distributions, resources, sourcePackage),
      'python_paths': ['python', 'site-packages', 'python/X-AnyLabeling'],
      'dll_dirs': nativeDirectories(records), 'preload_dlls': preloads,
      'source_files': [record for record in records if record['path'].startswith('python/')
                       and record['path'].endswith('.py')],
      'runtime_files': [record for record in records if record['path'].startswith(
        ('python/', 'site-packages/', 'native/'))],
      'native_dlls': [record for record in records if record['path'].lower().endswith('.dll')],
    }
    admissionBootloader = None
    if args.core_admission_bootloader:
      path, digest = args.core_admission_bootloader
      admissionBootloader = Path(path).absolute()
      metadata['admission_bootloader_sha256'] = contract.sha256(digest)
    upgradeLauncher = None
    if args.core_upgrade_launcher:
      path, digest = args.core_upgrade_launcher
      if any(not (core / 'python' / name).is_file() for name in ('core_update.py', 'core_update_transaction.py')):
        raise BuildConfigError('The fixed application source does not implement the stable Core upgrade entry')
      upgradeLauncher = Path(path).absolute()
      metadata['core_update_launcher_sha256'] = contract.sha256(digest)
    contract.validate_core(metadata)
    writeCanonical(core / contract.CORE_FILE, metadata, encoder=contract.canonical_json,
                    maximumBytes=contract.MAX_METADATA)
    archives = output / 'archives'
    archives.mkdir()
    reuse = (readReuseSource(args.reuse_root.resolve(), contract, set(metadata['catalog']))
             if args.reuse_root else None)
    if reuse:
      validateReuseCore(reuse, metadata)
    reusedArchives, reuseReports = {}, []
    manifests, freshManifests = {}, {}
    for name, declaration in metadata['catalog'].items():
      root = modules / name
      files = fileRecords(root / 'payload')
      manifest = {
        'protocol_version': contract.PROTOCOL_VERSION, 'module_api': contract.MODULE_API,
        'type': 'visionworkshop-module', 'version': args.core_version, 'module_id': name,
        'python': lock['python'], 'build': build,
        'core_versions': {'min': minimum, 'max_exclusive': maximum},
        'dependency_lock_sha256': metadata['dependency_lock_sha256'],
        **{key: declaration[key] for key in ('kind', 'requires', 'distributions', 'import_roots')},
        'python_paths': ['site-packages'] if declaration['distributions'] or declaration['import_roots'] else [],
        'dll_dirs': nativeDirectories(files, modulePayload=True), 'resources': resources.get(name, {}),
        'files': files, 'expanded_size': sum(record['size'] for record in files),
      }
      contract.validate_manifest(manifest, metadata)
      writeCanonical(root / contract.MANIFEST_FILE, manifest, encoder=contract.canonical_json,
                      maximumBytes=contract.MAX_METADATA)
      freshManifests[name] = manifest
      loader.writeReport(reports / 'fresh-module-manifests.json', freshManifests)
      if reuse:
        originalRoot = output / 'source-module-staging' / name
        selected, selection = selectSourceStaging(
          reuse, name, root / 'payload', manifest, metadata, originalRoot / 'payload', contract,
          distributions, provenance, reports / 'module-reuse-receipts' / name)
        loader.writeReport(reports / ('module-reuse-selection-' + name + '.json'), selection)
        destination = archives / (name + '-' + args.core_version + '.zip')
        manifest, reusedArchives[name], evidence, originalBytes = reuseArchive(
          reuse, name, originalRoot / 'payload', selected, metadata, destination, contract)
        (originalRoot / contract.MANIFEST_FILE).write_bytes(originalBytes)
        evidence['staging_selection'] = selection
        reuseReports.append(evidence)
      manifests[name] = manifest
    contract.validate_module_set(metadata, manifests)
    loader.writeReport(reports / 'module-manifests.json', manifests)
    loader.writeReport(reports / 'module-reuse-validation.json', {
      'enabled': reuse is not None, 'files': reuseReports,
      'source_receipt': reuse['receipt'] if reuse else None,
      'scope': 'Original ZIP verification; the new Core and full EXE matrix are independent'})
    buildFrozenCore(args.build_python.resolve(), buildInfo, core, metadata, output, reports,
                     Path(branding['icon_source']), crtRoot, crtProfile,
                     admissionBootloader=admissionBootloader, upgradeLauncher=upgradeLauncher)
    records = fileRecords(core)
    pythonFiles = [record for record in records if loader.isInterpreterFile(Path(record['path']))]
    if {record['path'] for record in pythonFiles} != {'_internal/python312.dll', '_internal/python3.dll'}:
      raise BuildConfigError('Core contains an unexpected second interpreter executable or DLL')
    if fileHash(core / '_internal/python312.dll') != fileHash(selectedPython):
      raise BuildConfigError('Core CPython DLL differs from the selected build Python')
    nativeInventory = [record for record in records if record['path'].lower().endswith('.dll')]
    # Check frozen stdlib DLLs too without changing the already embedded Core JSON.
    contract.validate_module_set(dict(metadata, native_dlls=nativeInventory), manifests)
    loader.writeReport(reports / 'core-native-inventory.json', {
      'status': 'PASS', 'scope': 'All Core DLLs, including frozen _internal, against every module owner',
      'files': nativeInventory})
    loader.writeReport(reports / 'core-files.json', {'files': records})
    result['core_archive'] = compressPackage(core, archives / ('VisionWorkshop-Core-' + args.core_version + '.zip'),
                                             prefix='VisionWorkshop', maximumBytes=contract.MAX_ARCHIVE_BYTES)
    result['module_archives'] = []
    for name in contract.dependency_order(manifests):
      artifact = (reusedArchives[name] if name in reusedArchives else
                  compressPackage(modules / name, archives / (name + '-' + args.core_version + '.zip'),
                                    maximumBytes=contract.MAX_ARCHIVE_BYTES))
      result['module_archives'].append(dict(artifact, module_id=name,
                                            manifest_sha256=contract.manifest_digest(manifests[name])))
    result.update(core=metadata, core_sha256=contract.manifest_digest(metadata),
                  dependency_lock=lock,
                  release_gate='NOT_QUALIFIED', compatibility_findings=lock['compatibility_findings'],
                  core_bytes=sum(record['size'] for record in records),
                  unique_python_files=pythonFiles, source=sourceState, vendor_sources=vendor,
                  profile_sha256=fileHash(args.profile),
                  readline_compatibility=readline,
                  auxiliary_payload_compatibility=auxiliary,
                  module_reuse={'enabled': reuse is not None, 'files': reuseReports},
                  module_builds={name: manifest['build'] for name, manifest in manifests.items()},
                  packager=packagerState, branding=branding)
    result['module_index'] = writeModuleIndex(archives / INDEX_FILE, result, contract)
    copyFile(archives / INDEX_FILE, reports / INDEX_FILE)
    result['status'] = 'BUILT'
    return result
  except Exception as error:
    result.update(error=str(error), traceback=traceback.format_exc())
    raise
  finally:
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    loader.writeReport(reports / 'modular-build-summary.json', result)


def parseArgs(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('operation', choices=('prepare', 'crt', 'assets', 'build'))
  parser.add_argument('--profile', type=Path, default=PROFILE)
  parser.add_argument('--source-root', type=Path)
  parser.add_argument('--assets-root', type=Path)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--build-python', type=Path)
  parser.add_argument('--runtime-python', type=Path)
  parser.add_argument('--install-report', type=Path, action='append', default=[])
  parser.add_argument('--torch-install-report', type=Path)
  parser.add_argument('--crt-root', type=Path)
  parser.add_argument('--reuse-root', type=Path,
                      help='Optional exact completed-run artifacts; absent means build every module ZIP')
  parser.add_argument('--core-admission-bootloader', nargs=2, metavar=('RUNW.EXE', 'SHA256'),
                      help='Build a guarded protocol-4 Core using a pinned local bootloader')
  parser.add_argument('--core-upgrade-launcher', nargs=2, metavar=('LAUNCHER.EXE', 'SHA256'),
                      help='Include the pinned stable upgrade and recovery entry for a guarded Core')
  parser.add_argument('--core-version', default='0.0.0')
  parser.add_argument('--max-core-version', default='0.0.1')
  parser.add_argument('--build-id', default=time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
  args = parser.parse_args(argv)
  if args.core_admission_bootloader and args.operation != 'build':
    parser.error('--core-admission-bootloader is only for a protocol-4 candidate build')
  if args.core_upgrade_launcher and not args.core_admission_bootloader:
    parser.error('--core-upgrade-launcher requires --core-admission-bootloader')
  if args.operation in ('assets', 'build') and (args.source_root is None or args.assets_root is None):
    parser.error('--source-root and an isolated --assets-root are required for assets/build')
  if args.operation == 'crt' and args.source_root is None:
    parser.error('--source-root is required to verify the shared CRT contract')
  if args.operation == 'build' and (not args.install_report or any(getattr(args, field) is None
      for field in ('build_python', 'runtime_python', 'torch_install_report', 'crt_root'))):
    parser.error('build requires build/runtime Python, installation reports and the prepared official CRT')
  return args


def main(argv=None) -> int:
  args = parseArgs(argv)
  operations = {'prepare': prepareInputs, 'crt': prepareCrt, 'assets': prepareAssets, 'build': buildCandidate}
  result = operations[args.operation](args)
  print(json.dumps({'operation': args.operation, 'status': result.get('status', 'PREPARED'),
                    'output': str(args.output)}, ensure_ascii=False), flush=True)
  return 0
