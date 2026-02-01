# Setup environment variables for NKON Monitor
# These variables are stored in the Windows Registry for the current User
# No changes to system files or admin rights required.

Write-Host "--- NKON Monitor Setup ---" -ForegroundColor Cyan

$token = Read-Host "Enter TELEGRAM_BOT_TOKEN"
if ([string]::IsNullOrWhiteSpace($token)) {
    Write-Host "Token cannot be empty!" -ForegroundColor Red
    exit 1
}

$chat_ids = Read-Host "Enter TELEGRAM_CHAT_IDS (comma separated)"
if ([string]::IsNullOrWhiteSpace($chat_ids)) {
    Write-Host "Chat IDs cannot be empty!" -ForegroundColor Red
    exit 1
}

$min_cap = Read-Host "Enter MIN_CAPACITY_AH (Default: 200)"
if ([string]::IsNullOrWhiteSpace($min_cap)) { $min_cap = "200" }

$threshold = Read-Host "Enter PRICE_ALERT_THRESHOLD (Default: 5)"
if ([string]::IsNullOrWhiteSpace($threshold)) { $threshold = "5" }

# Set Environment Variables (User Scope)
[System.Environment]::SetEnvironmentVariable('TELEGRAM_BOT_TOKEN', $token, 'User')
[System.Environment]::SetEnvironmentVariable('TELEGRAM_CHAT_IDS', $chat_ids, 'User')
[System.Environment]::SetEnvironmentVariable('MIN_CAPACITY_AH', $min_cap, 'User')
[System.Environment]::SetEnvironmentVariable('PRICE_ALERT_THRESHOLD', $threshold, 'User')

Write-Host "`n[SUCCESS] Environment variables saved!" -ForegroundColor Green
Write-Host "IMPORTANT: Please restart your terminal or VS Code for changes to take effect." -ForegroundColor Yellow
Write-Host "You can now safely delete any .env or config.json files." -ForegroundColor Gray
