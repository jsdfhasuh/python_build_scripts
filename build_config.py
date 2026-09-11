"""Opt-in branding configuration for the VisionWorkshop portable target.

Default builds do not use this module. Overrides are applied after the legacy
configuration expansion, so user-facing names are never expanded as shell or
environment expressions. This module has no build, network or publication side effects.
"""

import copy
import hashlib
import io
import json
import os
import re
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from pathlib import PureWindowsPath


SUPPORTED_TARGET = 'emo-vision-train'
PROFILE_FIELDS = {
  'schema_version', 'target', 'program_name', 'icon_path', 'release_asset_name',
  'runtime_branding_path',
  'updater_program_name', 'legacy_program_names',
}
MANAGED_OPTIONS = {
  '--name', '--icon', '--distpath', '--workpath', '--specpath', '--onefile', '--onedir',
}
RESERVED_NAME = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', re.I)
VARIABLE = re.compile(r'\$\{([^{}]+)\}')
MAX_ICON_BYTES = 16 * 1024 * 1024


class BuildConfigError(ValueError):
  """An invalid or unsupported branding request."""


def readJsonObject(path: Path) -> dict:
  def uniqueKeys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
      if key in result:
        raise BuildConfigError(f'Duplicate JSON key: {key}')
      result[key] = value
    return result

  try:
    with path.open(encoding='utf-8-sig') as stream:
      result = json.load(stream, object_pairs_hook=uniqueKeys)
  except (OSError, ValueError) as exc:
    raise BuildConfigError(f'Cannot read JSON configuration {path}: {exc}') from exc
  if not isinstance(result, dict):
    raise BuildConfigError(f'Configuration must be a JSON object: {path}')
  return result


def expandLegacyValues(value: object) -> object:
  if isinstance(value, str):
    return os.path.expandvars(value)
  if isinstance(value, list):
    return [expandLegacyValues(item) for item in value]
  if isinstance(value, dict):
    return {key: expandLegacyValues(item) for key, item in value.items()}
  return value


def requireText(value: object, label: str) -> str:
  if not isinstance(value, str) or not value or value != value.strip():
    raise BuildConfigError(f'{label} must be non-empty text without surrounding whitespace')
  return value


def validateFileName(value: object, label: str = 'Filename') -> str:
  name = requireText(value, label)
  if name in ('.', '..') or name[-1] in '. ' or name.startswith('-'):
    raise BuildConfigError(f'{label} is not a safe Windows filename: {name!r}')
  if any(ord(char) < 32 or ord(char) == 127 or char in '<>:"/\\|?*' for char in name):
    raise BuildConfigError(f'{label} contains a path separator or forbidden character: {name!r}')
  if RESERVED_NAME.match(name):
    raise BuildConfigError(f'{label} is a reserved Windows device name: {name!r}')
  try:
    units = len(name.encode('utf-16-le')) // 2
  except UnicodeEncodeError as exc:
    raise BuildConfigError(f'{label} contains invalid Unicode') from exc
  if units > 255:
    raise BuildConfigError(f'{label} is longer than 255 UTF-16 code units')
  return name


def validateProgramName(value: object) -> str:
  name = validateFileName(value, 'Program name')
  if name.lower().endswith('.exe'):
    raise BuildConfigError('Program name must not include the .exe extension')
  validateFileName(f'{name}.exe', 'Executable filename')
  return name


def expandTemplate(value: str, variables: dict[str, str], label: str) -> str:
  def replace(match: re.Match) -> str:
    key = match.group(1)
    if key not in variables or not variables[key]:
      raise BuildConfigError(f'{label}: unresolved or unsupported variable ${{{key}}}')
    return variables[key]

  # A replacement is not recursively expanded; a dollar sign in a name is literal.
  result = VARIABLE.sub(replace, value)
  if '${' in VARIABLE.sub('', value):
    raise BuildConfigError(f'{label}: malformed template variable')
  return result


def resolveResourcePath(value: object, root: Path, sourceRoot: str, label: str) -> Path:
  text = requireText(value, label)
  text = expandTemplate(text, {
    'PACKAGER_ROOT': str(root), 'SOURCE_ROOT': sourceRoot,
  }, label)
  path = Path(text)
  if not path.is_absolute():
    path = root / path
  return path.resolve()


def validateIcon(path: Path) -> str:
  if path.suffix.lower() != '.ico' or not path.is_file():
    raise BuildConfigError(f'Icon must be an existing .ico file: {path}')
  size = path.stat().st_size
  if size < 22 or size > MAX_ICON_BYTES:
    raise BuildConfigError(f'ICO size is invalid (22 bytes to 16 MiB required): {path}')
  with path.open('rb') as stream:
    data = stream.read(MAX_ICON_BYTES + 1)
  if not 22 <= len(data) <= MAX_ICON_BYTES:
    raise BuildConfigError(f'ICO changed or has an invalid size: {path}')
  reserved, imageType, count = struct.unpack_from('<HHH', data)
  if reserved != 0 or imageType != 1 or not 1 <= count <= 256:
    raise BuildConfigError(f'Invalid ICO header: {path}')
  tableEnd = 6 + 16 * count
  if len(data) < tableEnd:
    raise BuildConfigError(f'Truncated ICO directory: {path}')
  try:
    from PIL import Image
  except ImportError as exc:
    raise BuildConfigError(
      'ICO decoding requires Pillow in the build environment. Use the target project\'s '
      'existing Pillow dependency, or install Pillow before checking the icon.'
    ) from exc

  spans = []
  for index in range(count):
    start = 6 + 16 * index
    width, height, _, entryReserved, _, _, length, offset = struct.unpack_from(
      '<BBBBHHII', data, start,
    )
    if entryReserved or length == 0 or offset < tableEnd or offset + length > len(data):
      raise BuildConfigError(f'Invalid ICO image bounds at entry {index}: {path}')
    if any(offset < end and offset + length > begin for begin, end in spans):
      raise BuildConfigError(f'Overlapping ICO images at entry {index}: {path}')
    spans.append((offset, offset + length))
    frame = data[offset:offset + length]
    expectedSize = (width or 256, height or 256)
    if frame.startswith(b'\x89PNG\r\n\x1a\n'):
      if len(frame) < 33 or frame[12:16] != b'IHDR':
        raise BuildConfigError(f'Invalid PNG header in ICO entry {index}: {path}')
      actualSize = struct.unpack_from('>II', frame, 16)
    else:
      if len(frame) < 40:
        raise BuildConfigError(f'Truncated DIB header in ICO entry {index}: {path}')
      headerSize, dibWidth, dibHeight = struct.unpack_from('<Iii', frame)
      if headerSize < 40 or headerSize > len(frame) or dibHeight % 2:
        raise BuildConfigError(f'Invalid DIB header in ICO entry {index}: {path}')
      actualSize = (dibWidth, dibHeight // 2)
    if actualSize != expectedSize:
      raise BuildConfigError(f'ICO dimensions disagree with entry {index}: {path}')
    # Decode each entry separately, including duplicate-sized frames.
    single = struct.pack('<HHH', 0, 1, 1)
    single += data[start:start + 8] + struct.pack('<II', length, 22)
    single += data[offset:offset + length]
    try:
      with Image.open(io.BytesIO(single)) as image:
        image.load()
        if image.format != 'ICO' or image.size != (width or 256, height or 256):
          raise BuildConfigError(f'ICO dimensions disagree with entry {index}: {path}')
    except (OSError, ValueError, SyntaxError, EOFError, struct.error) as exc:
      raise BuildConfigError(f'Cannot decode ICO entry {index}: {path}: {exc}') from exc
  return hashlib.sha256(data).hexdigest()


def addRuntimeBranding(config: dict, path: Path) -> None:
  import build

  if path.name != 'branding.json':
    raise BuildConfigError('Runtime branding configuration must be named branding.json')
  data = readJsonObject(path)
  if data.keys() - {'display_name', 'window_icon'}:
    raise BuildConfigError('Runtime branding supports only display_name and window_icon')
  name = requireText(data.get('display_name'), 'Runtime display name')
  if len(name) > 80 or not name.isprintable():
    raise BuildConfigError('Runtime display name must be printable and at most 80 characters')
  text = requireText(data.get('window_icon'), 'Runtime window icon').replace('\\', '/')
  relative = PureWindowsPath(text)
  if relative.drive or relative.root or '..' in relative.parts or ':' in text:
    raise BuildConfigError('Runtime window icon must be relative without parent traversal')
  for part in relative.parts:
    validateFileName(part, 'Runtime icon path component')
  icon = path.parent.joinpath(*relative.parts).resolve()
  if not icon.is_relative_to(path.parent):
    raise BuildConfigError('Runtime window icon cannot escape the branding directory')
  iconSha = validateIcon(icon)
  mappings = config.get('add_data', [])
  if not isinstance(mappings, list) or not all(isinstance(item, str) for item in mappings):
    raise BuildConfigError('main.add_data must be a list of strings')
  targets = (PureWindowsPath('branding.json'), relative)
  for item in mappings:
    source, destination = build.split_add_data(item)
    sourcePath = Path(source)
    destinationPath = PureWindowsPath(destination)
    for target in targets:
      if sourcePath.is_dir() and target.is_relative_to(destinationPath):
        collision = sourcePath.joinpath(*target.relative_to(destinationPath).parts).exists()
      else:
        collision = target == destinationPath / sourcePath.name
      if collision:
        raise BuildConfigError(f'Runtime branding conflicts with existing add_data: {item}')
  config['add_data'] = [*mappings, f'{path}:.', f'{icon}:{relative.parent.as_posix()}']
  config['runtime_branding'] = {
    'display_name': name, 'window_icon': relative.as_posix(),
    'config_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    'window_icon_sha256': iconSha,
  }


def validateExtraArgs(config: dict, label: str) -> None:
  arguments = config.get('extra_args', []) or []
  if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
    raise BuildConfigError(f'{label}.extra_args must be a list of strings')
  for argument in arguments:
    option = argument.split('=', 1)[0]
    if option.startswith('--'):
      if option == '--' or any(managed.startswith(option) for managed in MANAGED_OPTIONS):
        raise BuildConfigError(f'{label}.extra_args conflicts with managed option: {argument}')
    elif option.startswith('-'):
      # PyInstaller/argparse also accepts attached values and short-option clusters.
      if len(option) > 2 or option in ('-n', '-i', '-F', '-D'):
        raise BuildConfigError(
          f'{label}.extra_args: use unambiguous long options, not {argument!r}'
        )


def resolveAssetName(template: str, programName: str, target: str, releaseTag: str) -> str:
  tag = requireText(releaseTag, 'Release tag')
  result = expandTemplate(template, {
    'RELEASE_TAG': tag, 'PROGRAM_NAME': programName, 'TARGET': target,
  }, 'ZIP name')
  validateFileName(result, 'ZIP filename')
  if not result.lower().endswith('.zip'):
    raise BuildConfigError('Portable release asset must have the .zip extension')
  return result


@dataclass(frozen=True)
class ResolvedBuild:
  config: dict
  target: str
  originalName: str
  iconSha256: str | None
  assetTemplate: str
  packagerRoot: Path

  @property
  def programName(self) -> str:
    return self.config['name']

  @property
  def renamed(self) -> bool:
    return self.programName.casefold() != self.originalName.casefold()

  @property
  def legacyProgramNames(self) -> list[str]:
    return self.config.get('legacy_program_names', [])

  @property
  def updateCompatibility(self) -> str:
    if not self.renamed:
      return 'unchanged-name-not-retested'
    if self.programName == 'VisionWorkshop' and self.originalName in self.legacyProgramNames:
      return 'legacy-launcher-contract'
    return 'unverified'

  @property
  def fingerprint(self) -> str:
    payload = {'config': self.config, 'icon_sha256': self.iconSha256}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()

  def assetName(self, releaseTag: str, manifestName: str = 'manifest.json') -> str:
    result = resolveAssetName(self.assetTemplate, self.programName, self.target, releaseTag)
    validateFileName(manifestName, 'Manifest filename')
    if result.casefold() == manifestName.casefold():
      raise BuildConfigError('ZIP and manifest filenames must not collide')
    return result

  def assertPublicationAllowed(self) -> None:
    if (self.renamed and (self.config.get('updater') or {}).get('enabled')
        and self.updateCompatibility != 'legacy-launcher-contract'):
      raise BuildConfigError(
        'EXE rename has unverified updater compatibility. Build locally only; do not '
        'publish to an existing update channel. Changing a repo, tag or manifest is '
        'not evidence of compatibility. This does not disable runtime updates.'
      )

  def summary(self) -> dict:
    return {
      'target': self.target,
      'program_name': self.programName,
      'original_program_name': self.originalName,
      'updater_program_name': (self.config.get('updater') or {}).get('name'),
      'legacy_program_names': self.legacyProgramNames,
      'icon_path': self.config.get('icon'),
      'icon_sha256': self.iconSha256,
      'release_asset_template': self.assetTemplate,
      'config_sha256': self.fingerprint,
      'distribution': 'portable-directory',
      'window_branding': ('bundled-not-runtime-verified' if self.config.get('runtime_branding')
                          else 'not-adapted-by-packager'),
      'runtime_branding': self.config.get('runtime_branding'),
      'update_compatibility': self.updateCompatibility,
      'runtime_updates_disabled': False,
    }


def resolveBuildConfig(
  configPath: Path,
  *,
  profilePath: str | None = None,
  programName: str | None = None,
  iconPath: str | None = None,
  releaseAssetName: str | None = None,
  packagerRoot: Path | None = None,
) -> ResolvedBuild:
  root = (packagerRoot or Path(__file__).resolve().parent).resolve()
  target = configPath.stem
  if target != SUPPORTED_TARGET:
    raise BuildConfigError(f'Branding is currently supported only for {SUPPORTED_TARGET}')
  raw = readJsonObject(configPath)
  cfg = expandLegacyValues(copy.deepcopy(raw))
  if cfg.get('onefile', True) is not False:
    raise BuildConfigError('VisionWorkshop branding requires an onedir main application')
  installer = cfg.get('installer') or {}
  if not isinstance(installer, dict):
    raise BuildConfigError('installer configuration must be an object')
  if installer.get('enabled'):
    raise BuildConfigError('Installer targets are not supported by portable branding')
  entry = requireText(cfg.get('entry'), 'Entry script')
  if Path(entry).suffix.lower() == '.spec':
    raise BuildConfigError('Branding does not support hand-written .spec files')
  sourceRoot = os.environ.get('SOURCE_ROOT', '')
  if sourceRoot:
    sourceRoot = str(Path(sourceRoot).resolve())
  overlay = {}
  if profilePath is not None:
    profileFile = resolveResourcePath(profilePath, root, sourceRoot, 'Branding profile')
    overlay = readJsonObject(profileFile)
    unknown = overlay.keys() - PROFILE_FIELDS
    if unknown:
      raise BuildConfigError(f'Unsupported branding profile fields: {sorted(unknown)}')
    if type(overlay.get('schema_version')) is not int or overlay['schema_version'] != 1:
      raise BuildConfigError('Branding profile schema_version must be 1')
    if overlay.get('target') != target:
      raise BuildConfigError(f'Branding profile target must equal {target}')

  for key, value in (
    ('program_name', programName), ('icon_path', iconPath),
    ('release_asset_name', releaseAssetName),
  ):
    if value is not None:
      overlay[key] = value
  originalName = validateProgramName(cfg.get('name'))
  cfg['name'] = validateProgramName(overlay.get('program_name', originalName))
  updater = cfg.get('updater') or {}
  if not isinstance(updater, dict):
    raise BuildConfigError('updater configuration must be an object')
  if 'updater_program_name' in overlay:
    if not updater.get('enabled'):
      raise BuildConfigError('An updater name override requires an enabled updater')
    updater['name'] = validateProgramName(overlay['updater_program_name'])
  if updater.get('enabled'):
    updaterName = validateProgramName(updater.get('name', 'updater'))
    if cfg['name'].casefold() in (updaterName.casefold(), 'updater'):
      raise BuildConfigError('Program name collides with the updater task or updater.exe')
    if updater.get('onefile', True) is not True:
      raise BuildConfigError('Portable branding requires a onefile updater')
    if Path(str(updater.get('entry', 'updater.py'))).suffix.lower() == '.spec':
      raise BuildConfigError('Branding does not support a hand-written updater .spec')
    validateExtraArgs(updater, 'updater')
  validateExtraArgs(cfg, 'main')

  iconSha = None
  if 'icon_path' in overlay:
    icon = resolveResourcePath(overlay['icon_path'], root, sourceRoot, 'Icon path')
    iconSha = validateIcon(icon)
    cfg['icon'] = str(icon)
  elif cfg.get('icon'):
    # Preserve legacy icon-path semantics, but prove any icon used in a custom build.
    icon = Path(cfg['icon']).resolve()
    iconSha = validateIcon(icon)
    cfg['icon'] = str(icon)

  if 'runtime_branding_path' in overlay:
    brandingPath = resolveResourcePath(
      overlay['runtime_branding_path'], root, sourceRoot, 'Runtime branding path',
    )
    addRuntimeBranding(cfg, brandingPath)
    if 'updater_program_name' in overlay:
      addRuntimeBranding(updater, brandingPath)
      updater['icon'] = cfg.get('icon')

  if 'legacy_program_names' in overlay:
    names = overlay['legacy_program_names']
    if not isinstance(names, list) or not names:
      raise BuildConfigError('legacy_program_names must be a non-empty list')
    names = [validateProgramName(name) for name in names]
    if cfg['name'] != 'VisionWorkshop':
      raise BuildConfigError('Legacy launchers currently support only VisionWorkshop')
    if originalName not in names:
      raise BuildConfigError('Legacy launchers must include the original program name')
    if len({name.casefold() for name in names}) != len(names):
      raise BuildConfigError('Duplicate legacy program names')
    reserved = {cfg['name'].casefold(), updater.get('name', 'updater').casefold(), 'updater'}
    if any(name.casefold() in reserved for name in names):
      raise BuildConfigError('Legacy launcher collides with main/updater executable')
    launcher = root / 'legacy_launcher.py'
    if not launcher.is_file():
      raise BuildConfigError(f'Legacy launcher source is missing: {launcher}')
    cfg['legacy_program_names'] = names
    cfg['legacy_launcher_entry'] = str(launcher)

  # Asset templates are intentionally not expanded by os.path.expandvars.
  assetTemplate = requireText(
    overlay.get('release_asset_name', raw.get('release_asset_name')),
    'Release asset template',
  )
  resolveAssetName(assetTemplate, cfg['name'], target, 'preview')
  cfg['release_asset_name'] = assetTemplate
  return ResolvedBuild(cfg, target, originalName, iconSha, assetTemplate, root)


@dataclass(frozen=True)
class BuildContext:
  root: Path
  target: str
  buildId: str

  def containedPath(self, *parts: str) -> Path:
    path = self.root.joinpath(*parts)
    if not path.resolve().is_relative_to(self.root.resolve()):
      raise BuildConfigError('Branding output must stay inside the packager directory')
    return path

  @property
  def workRoot(self) -> Path:
    return self.containedPath('build', 'branding', self.target, self.buildId)

  @property
  def distRoot(self) -> Path:
    return self.containedPath('dist', 'branding', self.target, self.buildId)

  def specPath(self, label: str) -> Path:
    return self.workRoot / 'spec' / label

  def workPath(self, label: str) -> Path:
    return self.workRoot / 'work' / label

  def prepare(self, resolved: ResolvedBuild) -> None:
    if self.distRoot.exists():
      raise BuildConfigError(f'Isolated dist already exists; refuse reuse: {self.distRoot}')
    self.workRoot.mkdir(parents=True, exist_ok=False)
    configPath = self.workRoot / 'effective-config.json'
    configPath.write_text(
      json.dumps(resolved.config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
    )


def createBuildContext(resolved: ResolvedBuild) -> BuildContext:
  stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
  return BuildContext(resolved.packagerRoot, resolved.target, f'{stamp}-{uuid.uuid4().hex[:12]}')
