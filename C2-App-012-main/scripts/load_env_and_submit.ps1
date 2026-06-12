$param(
  [string]$ScriptToRun = "scripts\submit_log.py"
)

$envFile = Join-Path (Get-Location) '.env'
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -and ($_ -notmatch '^\s*#')) {
      $parts = $_ -split '=',2
      if ($parts.Count -eq 2) {
        $name = $parts[0].Trim()
        $val = $parts[1].Trim()
        Set-Item -Path "Env:\$name" -Value $val
      }
    }
  }
}

Write-Output "[env] AI_LOG_SERVER=$env:AI_LOG_SERVER"
if ($ScriptToRun) {
  & scripts\_pyrun.cmd $ScriptToRun
}
