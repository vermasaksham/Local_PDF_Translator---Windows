# Locate the Tesseract that Chocolatey just installed, make sure the language
# data the app needs is present, and export both facts to later steps.
#
# Chocolatey's tesseract package ignores /InstallDir and always lands in the
# default location, so the install path is discovered rather than dictated.

$ErrorActionPreference = "Stop"

$candidates = @(
    "C:\Program Files\Tesseract-OCR",
    "C:\Program Files (x86)\Tesseract-OCR",
    "C:\Tesseract-OCR"
)
$root = $candidates | Where-Object { Test-Path (Join-Path $_ "tesseract.exe") } | Select-Object -First 1
if (-not $root) {
    throw "Tesseract was not found in any of: $($candidates -join ', ')"
}
Write-Host "Tesseract is installed at $root"

$tessdata = Join-Path $root "tessdata"
New-Item -ItemType Directory -Force -Path $tessdata | Out-Null

# eng and osd normally ship with the package; deu and hin never do.
foreach ($code in @("eng", "deu", "hin", "osd")) {
    $target = Join-Path $tessdata "$code.traineddata"
    if (Test-Path $target) {
        Write-Host "$code.traineddata already present"
        continue
    }
    $url = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/$code.traineddata"
    Write-Host "Downloading $code.traineddata"
    Invoke-WebRequest -Uri $url -OutFile $target
}

$exe = Join-Path $root "tesseract.exe"
& $exe --list-langs

"TESSERACT_DIR=$root"     | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
"LPT_TESSERACT_EXE=$exe"  | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
