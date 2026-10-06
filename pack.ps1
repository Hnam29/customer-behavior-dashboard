<#
.SYNOPSIS
    Đóng gói dự án customer_behavior thành file ZIP để gửi đối tác.

.DESCRIPTION
    Script loại trừ các thư mục/file không cần thiết (.venv, __pycache__,
    airflow logs/config/plugins, data, build.log) rồi tạo file ZIP.

.USAGE
    Mở PowerShell tại thư mục dự án rồi chạy:
        .\pack.ps1

    Hoặc chỉ định tên file đầu ra:
        .\pack.ps1 -OutputName "customer_behavior_v1.0"
#>

param(
    [string]$OutputName = "customer_behavior_$(Get-Date -Format 'yyyyMMdd')"
)

# ── Đường dẫn ──────────────────────────────────────────────────────────────
$ProjectDir = $PSScriptRoot                   # thư mục chứa script này
$OutputDir  = Split-Path $ProjectDir -Parent  # thư mục cha (Downloads)
$ZipPath    = Join-Path $OutputDir "$OutputName.zip"

# ── Danh sách loại trừ ─────────────────────────────────────────────────────
$Excludes = @(
    ".venv",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "airflow\logs",
    "airflow\config",
    "airflow\plugins",
    "data",
    "build.log",
    "pack.ps1",       # không cần đưa script đóng gói vào gói
    "*.zip"
)

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Đóng gói dự án customer_behavior" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Nguồn : $ProjectDir"
Write-Host "  Đích   : $ZipPath"
Write-Host ""

# ── Xoá file zip cũ nếu có ────────────────────────────────────────────────
if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
    Write-Host "  Đã xoá file ZIP cũ." -ForegroundColor Yellow
}

# ── Thu thập file cần đưa vào ─────────────────────────────────────────────
Write-Host "  Đang quét file..." -ForegroundColor Gray

$AllFiles = Get-ChildItem -Path $ProjectDir -Recurse -File

$FilesToPack = $AllFiles | Where-Object {
    $relativePath = $_.FullName.Substring($ProjectDir.Length + 1)

    $excluded = $false
    foreach ($pattern in $Excludes) {
        # Khớp tên file
        if ($_.Name -like $pattern) { $excluded = $true; break }
        # Khớp đường dẫn tương đối (thư mục con)
        if ($relativePath -like "$pattern\*" -or $relativePath -like "$pattern/*") {
            $excluded = $true; break
        }
        # Khớp chính xác thư mục đầu
        if ($relativePath.StartsWith("$pattern\") -or $relativePath.StartsWith("$pattern/")) {
            $excluded = $true; break
        }
    }
    -not $excluded
}

$Count = ($FilesToPack | Measure-Object).Count
Write-Host "  Tìm thấy $Count file sẽ được đóng gói." -ForegroundColor Gray
Write-Host ""

# ── Tạo ZIP ───────────────────────────────────────────────────────────────
Add-Type -Assembly System.IO.Compression.FileSystem

$ZipStream = [System.IO.Compression.ZipFile]::Open($ZipPath, 'Create')

try {
    foreach ($file in $FilesToPack) {
        $entryName = "$OutputName\" + $file.FullName.Substring($ProjectDir.Length + 1)
        # Dùng dấu / thay \ cho tương thích cross-platform
        $entryName = $entryName.Replace("\", "/")

        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $ZipStream, $file.FullName, $entryName,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
    Write-Host "  ✅ Đóng gói thành công!" -ForegroundColor Green
}
finally {
    $ZipStream.Dispose()
}

# ── Kết quả ───────────────────────────────────────────────────────────────
$ZipInfo = Get-Item $ZipPath
$SizeMB  = [math]::Round($ZipInfo.Length / 1MB, 2)

Write-Host ""
Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host "  File ZIP : $ZipPath"
Write-Host "  Kích thước : $SizeMB MB"
Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Hướng dẫn cho đối tác:" -ForegroundColor White
Write-Host "  1. Giải nén file ZIP"
Write-Host "  2. Mở file HUONG_DAN_CAI_DAT.md và làm theo từng bước"
Write-Host ""
