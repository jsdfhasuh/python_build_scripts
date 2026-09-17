"""Protocol assets are uploaded to Draft and verified before publication."""

import hashlib
import json

from build_config import BuildConfigError
from path_boundary import ioPath
from update_protocol_build import ASSET_PREFIX, RELEASE_REPO


def artifactRecords(paths):
  records = {}
  for path in paths:
    digest = hashlib.sha256()
    size = 0
    with ioPath(path).open('rb') as stream:
      while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        digest.update(chunk)
    if not 0 < size < 2 * 1024**3 or path.name in records:
      raise BuildConfigError('Invalid/duplicate protocol asset or GitHub asset size exceeded')
    records[path.name] = {'size': size, 'digest': 'sha256:' + digest.hexdigest()}
  return records


def verifyUploaded(run, repo, release, expected, *, draft):
  if release.get('draft') is not draft or release.get('prerelease') is not False:
    raise BuildConfigError('Release audience/state changed; refusing publication')
  pages = json.loads(run(['gh', 'api', '--paginate', '--slurp',
    f'repos/{repo}/releases/{release["id"]}/assets?per_page=100']))
  actual = {}
  for page in pages:
    if not isinstance(page, list):
      raise BuildConfigError('Invalid GitHub asset pagination')
    for asset in page:
      if asset.get('name') in actual or asset.get('state') != 'uploaded':
        raise BuildConfigError('Duplicate/incomplete GitHub asset')
      actual[asset.get('name')] = {'size': asset.get('size'), 'digest': asset.get('digest')}
  if actual != expected:
    raise BuildConfigError('Uploaded assets differ in names, size or SHA-256; Draft retained')


def publishProtocolAssets(args, resolved, summary, output, notesPath, content, run, getRelease):
  repo = args.release_repo or resolved.config['release_repo']
  if repo != RELEASE_REPO:
    raise BuildConfigError('Protocol-3 publication repository is fixed')
  names = summary.get('protocol_asset_names')
  if not isinstance(names, list) or len(names) not in (3, 5):
    raise BuildConfigError('Missing protocol assets')
  paths = [output / name for name in names]
  expected = artifactRecords(paths)
  if expected != summary.get('protocol_assets'):
    raise BuildConfigError('Protocol assets changed after packaging')
  run(['gh', 'release', 'create', args.release_tag, *map(str, paths), '--draft',
       '--repo', repo, '--title', content.title, '--notes-file', str(notesPath)])
  draft = getRelease(repo, args.release_tag)
  if not draft or draft.get('tag_name') != args.release_tag:
    raise BuildConfigError('Cannot resolve newly-created Draft; no retry or overwrite attempted')
  verifyUploaded(run, repo, draft, expected, draft=True)
  if artifactRecords(paths) != expected:
    raise BuildConfigError('Local protocol assets changed during upload; Draft retained')
  run(['gh', 'release', 'edit', args.release_tag, '--repo', repo, '--draft=false', '--latest'])
  published = getRelease(repo, args.release_tag)
  if not published or published.get('id') != draft['id']:
    raise BuildConfigError('Published Release identity cannot be confirmed')
  verifyUploaded(run, repo, published, expected, draft=False)
