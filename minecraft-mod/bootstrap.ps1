$ErrorActionPreference = 'Stop'
$naparDestination = Join-Path $PSScriptRoot 'libs/carpet-26.2.jar'
New-Item -ItemType Directory -Force (Split-Path $naparDestination) | Out-Null
Invoke-WebRequest 'https://github.com/gnembon/fabric-carpet/releases/download/v26.2/fabric-carpet-26.2%2Bv260616.jar' -OutFile $naparDestination
if ((Get-FileHash $naparDestination -Algorithm SHA256).Hash -ne 'F6ADA912AF65C91536D4B0D80ADF26CC438253252DDAF259F2C6617AE471311C') {
    throw 'Carpet checksum mismatch; do not build'
}
