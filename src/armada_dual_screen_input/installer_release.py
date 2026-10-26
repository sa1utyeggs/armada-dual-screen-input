"""Public stable-release discovery for first installs, without REST API quotas.

GitHub's /releases/latest redirect selects the tag. Its HTTPS checksum asset
pins both downloads between review and installation. The existing bounded
downloader and manifest verifier still validate every file before execution.
"""
import hashlib
import re
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, build_opener

from .i18n import msg
from .updates import APP, REPO, STABLE, MAX_ARCHIVE, HTTPSRedirects, Release, UpdateError, limited_read

WEB = 'https://github.com/' + REPO


def open_release_url(url, *, method='GET'):
    return build_opener(HTTPSRedirects()).open(Request(url, method=method, headers={
        'User-Agent': APP + '-installer', 'Accept': '*/*',
    }), timeout=15)


def latest_install_release(*, opener=open_release_url):
    """Read public release links only; fail closed on missing or changed assets."""
    try:
        with opener(WEB + '/releases/latest') as response:
            final = urlsplit(response.geturl())
            prefix = '/' + REPO + '/releases/tag/'
            path = unquote(final.path)
            tag = path.removeprefix(prefix)
            if (final.scheme != 'https' or final.netloc != 'github.com' or final.query or final.fragment
                    or not path.startswith(prefix) or not tag.startswith('v')
                    or not 2 <= len(tag) <= 65 or not re.fullmatch(STABLE, tag[1:])):
                raise UpdateError(msg('update.invalid_release'))
        version = tag[1:]
        filename = f'{APP}-{version}-aarch64.tar.gz'
        download_root = WEB + '/releases/download/' + quote(tag, safe='') + '/'
        checksum_url = download_root + 'SHA256SUMS'
        archive_url = download_root + quote(filename, safe='')
        with opener(checksum_url) as response:
            checksums = limited_read(response, 65536)
        try:
            lines = checksums.decode('ascii').strip().splitlines()
        except UnicodeDecodeError:
            raise UpdateError(msg('update.checksum_mismatch')) from None
        fields = lines[0].split() if len(lines) == 1 else []
        if (len(fields) != 2 or fields[1] != filename
                or not re.fullmatch(r'[0-9a-f]{64}', fields[0])):
            raise UpdateError(msg('update.checksum_mismatch'))
        with opener(archive_url, method='HEAD') as response:
            length = response.headers.get('Content-Length', '')
            if not re.fullmatch(r'[0-9]{1,10}', length) or not 0 < int(length) <= MAX_ARCHIVE:
                raise UpdateError(msg('update.asset_invalid'))
            size = int(length)
        return Release(version, tag, archive_url, checksum_url, fields[0],
                       hashlib.sha256(checksums).hexdigest(), size, len(checksums))
    except UpdateError:
        raise
    except HTTPError as error:
        raise UpdateError(msg('update.http', code=error.code)) from error
    except Exception as error:
        raise UpdateError(msg('update.network')) from error
