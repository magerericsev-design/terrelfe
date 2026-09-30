#!/usr/bin/env bash
set -euo pipefail
TOOLS=/workspace/android-tools
mkdir -p "$TOOLS"
cd "$TOOLS"
if [[ ! -x "$TOOLS/jdk/bin/javac" ]]; then
  BASE=https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.8%2B9
  curl -fL "$BASE/OpenJDK21U-jdk_x64_linux_hotspot_21.0.8_9.tar.gz" -o jdk.tar.gz
  curl -fsSL "$BASE/OpenJDK21U-jdk_x64_linux_hotspot_21.0.8_9.tar.gz.sha256.txt" -o jdk.sha256
  python3 - <<'PY'
from pathlib import Path
import hashlib
assert hashlib.sha256(Path('jdk.tar.gz').read_bytes()).hexdigest() == Path('jdk.sha256').read_text().split()[0]
PY
  mkdir -p jdk
  tar -xzf jdk.tar.gz -C jdk --strip-components=1
fi
export JAVA_HOME="$TOOLS/jdk"
export PATH="$JAVA_HOME/bin:$PATH"
export ANDROID_HOME="$TOOLS/sdk"
export ANDROID_USER_HOME="$TOOLS/user"
export GRADLE_USER_HOME="$TOOLS/gradle-home"
mkdir -p "$ANDROID_USER_HOME" "$GRADLE_USER_HOME"
# Honor the cloud's proxy and trust certificates without weakening TLS verification.
python3 - <<'PY'
from pathlib import Path
import os, re, shutil, subprocess
from urllib.parse import urlsplit
p=Path('/workspace/android-tools')
lines=[]; options=[]
proxy=os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
if proxy:
    url=urlsplit(proxy)
    if url.username or url.password:
        raise RuntimeError('Authenticated proxy must be configured by the platform')
    for protocol in ('http','https'):
        for key,value in [('proxyHost',url.hostname),('proxyPort',url.port or 8080)]:
            lines.append(f'systemProp.{protocol}.{key}={value}')
            options.append(f'-D{protocol}.{key}={value}')
cert_file=os.environ.get('SSL_CERT_FILE')
if cert_file:
    store=p/'jdk-cloud-truststore'
    if not store.exists():
        shutil.copy2(Path(os.environ['JAVA_HOME'])/'lib/security/cacerts',store)
        for i,cert in enumerate(re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',Path(cert_file).read_text(),re.S)):
            file=p/f'cloud-cert-{i}.pem'; file.write_text(cert)
            subprocess.run(['keytool','-importcert','-noprompt','-alias',f'cloud-{i}','-file',str(file),'-keystore',str(store),'-storepass','changeit'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            file.unlink()
    for key,value in [('trustStore',str(store)),('trustStorePassword','changeit')]:
        lines.append(f'systemProp.javax.net.ssl.{key}={value}')
        options.append(f'-Djavax.net.ssl.{key}={value}')
# This is a dedicated task-owned Gradle home, not a user configuration directory.
(p/'gradle-home/gradle.properties').write_text('\n'.join(lines)+'\n')
(p/'java-options').write_text(' '.join(options))
PY
export JAVA_TOOL_OPTIONS="$(cat "$TOOLS/java-options")"
if [[ ! -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]]; then
  curl -fL https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -o commandline.zip
  curl -fsSL https://dl.google.com/android/repository/repository2-1.xml -o repository.xml
  python3 - <<'PY'
from pathlib import Path
import hashlib,zipfile,xml.etree.ElementTree as ET
for archive in ET.parse('repository.xml').getroot().iter('archive'):
    complete=archive.find('complete')
    if complete is not None and complete.findtext('url') == 'commandlinetools-linux-11076708_latest.zip':
        assert hashlib.sha1(Path('commandline.zip').read_bytes()).hexdigest() == complete.findtext('checksum')
        break
else:
    raise RuntimeError('Google archive checksum unavailable')
with zipfile.ZipFile('commandline.zip') as archive:
    archive.extractall('.')
parent=Path('sdk/cmdline-tools'); parent.mkdir(parents=True,exist_ok=True)
Path('cmdline-tools').rename(parent/'latest')
for tool in (parent/'latest/bin').iterdir(): tool.chmod(0o755)
PY
fi
python3 - <<'PY'
import os,subprocess
sdk=os.environ['ANDROID_HOME']
command=[sdk+'/cmdline-tools/latest/bin/sdkmanager','--sdk_root='+sdk]
subprocess.run(command+['--licenses'],input='y\n'*200,text=True,check=True)
subprocess.run(command+['platform-tools','platforms;android-35','build-tools;35.0.0'],check=True)
PY
printf 'sdk.dir=%s\n' "$ANDROID_HOME" > /workspace/terrelfe/android/local.properties
cd /workspace/terrelfe
python3 android/tools/prepare_assets.py
PYTHONDONTWRITEBYTECODE=1 python3 android/tests/test_backend.py
cd android
./gradlew --no-daemon :app:assembleDebug
