# Setup environment variables for NKON Monitor
# Choice between Windows Registry (Persistent) or .env file (Immediate/Portable)

Write-Host "--- NKON Monitor Setup ---" -ForegroundColor Cyan

# Helper to read from existing .env if present
function Get-CurrentFromEnv {
    param ([string]$Key)
    if (Test-Path ".env") {
        $line = Get-Content ".env" | Where-Object { $_ -match "^$Key=" }
        if ($line) {
            return $line.Split('=', 2)[1].Trim()
        }
    }
    return ""
}

function Read-UserVariable {
    param (
        [string]$Name,
        [string]$PromptText,
        [bool]$Required = $false,
        [string]$DefaultValue = ""
    )
    
    # Try .env first, then Registry
    $current = Get-CurrentFromEnv -Key $Name
    if ([string]::IsNullOrWhiteSpace($current)) {
        $current = [System.Environment]::GetEnvironmentVariable($Name, 'User')
    }

    $prompt = "$PromptText"
    
    if (-not [string]::IsNullOrWhiteSpace($current)) {
        # Mask sensitive data
        $display = $current
        if ($Name -like "*TOKEN*" -or $Name -like "*SECRET*") {
            if ($current.Length -gt 8) {
                $display = $current.Substring(0, 4) + "..." + $current.Substring($current.Length - 4)
            }
            else {
                $display = "***"
            }
        }
        $prompt += " [Current: $display]"
    }
    elseif (-not [string]::IsNullOrWhiteSpace($DefaultValue)) {
        $prompt += " [Default: $DefaultValue]"
    }
    
    $inputVal = Read-Host $prompt
    
    if ([string]::IsNullOrWhiteSpace($inputVal)) {
        if (-not [string]::IsNullOrWhiteSpace($current)) { return $current }
        if (-not [string]::IsNullOrWhiteSpace($DefaultValue)) { return $DefaultValue }
    }
    else {
        return $inputVal
    }
    
    if ($Required) {
        Write-Host "Error: $Name is required!" -ForegroundColor Red
        exit 1
    }
    return ""
}

Write-Host "`nStep 1: Choose storage method" -ForegroundColor Yellow
Write-Host "1) Windows Registry (Requires VS Code restart to apply changes)"
Write-Host "2) .env file (Applies changes immediately, recommended for testing)"
$storageChoice = Read-Host "Your choice (1 or 2, default is 2)"
if ([string]::IsNullOrWhiteSpace($storageChoice)) { $storageChoice = "2" }

$token = Read-UserVariable -Name "TELEGRAM_BOT_TOKEN" -PromptText "Enter TELEGRAM_BOT_TOKEN" -Required $true

Write-Host "`nStep 2: Configuration for Notifications" -ForegroundColor Yellow
$chat_ids_full = Read-UserVariable -Name "TELEGRAM_CHAT_IDS_FULL" -PromptText "Enter Chat IDs for FULL Reports (comma separated)"
$chat_ids_changes = Read-UserVariable -Name "TELEGRAM_CHAT_IDS_CHANGES_ONLY" -PromptText "Enter Chat IDs for CHANGES ONLY (comma separated)"

# Logic: Remove Changes IDs from Full IDs to avoid duplicates
if (-not [string]::IsNullOrWhiteSpace($chat_ids_full) -and -not [string]::IsNullOrWhiteSpace($chat_ids_changes)) {
    $full_list = $chat_ids_full -split ',' | ForEach-Object { $_.Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $changes_list = $chat_ids_changes -split ',' | ForEach-Object { $_.Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    
    $new_full_list = @()
    foreach ($id in $full_list) {
        if ($changes_list -notcontains $id) { $new_full_list += $id }
    }
    $chat_ids_full = $new_full_list -join ','
}

$min_cap = Read-UserVariable -Name "MIN_CAPACITY_AH" -PromptText "Enter MIN_CAPACITY_AH" -DefaultValue "200"
$threshold = Read-UserVariable -Name "PRICE_ALERT_THRESHOLD" -PromptText "Enter PRICE_ALERT_THRESHOLD" -DefaultValue "5"
$fetch_dates = Read-UserVariable -Name "FETCH_DELIVERY_DATES" -PromptText "Fetch Delivery Dates for Pre-orders? (true/false)" -DefaultValue "true"
$fetch_stock = Read-UserVariable -Name "FETCH_REAL_STOCK" -PromptText "Probe Real Stock Quantity? (true/false)" -DefaultValue "true"
$fetch_delay = Read-UserVariable -Name "DETAIL_FETCH_DELAY" -PromptText "Delay between detail requests (seconds)" -DefaultValue "2"

if ($storageChoice -eq "1") {
    # --- Option 1: Registry ---
    [System.Environment]::SetEnvironmentVariable('TELEGRAM_BOT_TOKEN', $token, 'User')
    [System.Environment]::SetEnvironmentVariable('TELEGRAM_CHAT_IDS', $null, 'User') 
    [System.Environment]::SetEnvironmentVariable('TELEGRAM_CHAT_IDS_FULL', $chat_ids_full, 'User')
    [System.Environment]::SetEnvironmentVariable('TELEGRAM_CHAT_IDS_CHANGES_ONLY', $chat_ids_changes, 'User')
    [System.Environment]::SetEnvironmentVariable('MIN_CAPACITY_AH', $min_cap, 'User')
    [System.Environment]::SetEnvironmentVariable('PRICE_ALERT_THRESHOLD', $threshold, 'User')
    [System.Environment]::SetEnvironmentVariable('FETCH_DELIVERY_DATES', $fetch_dates, 'User')
    [System.Environment]::SetEnvironmentVariable('FETCH_REAL_STOCK', $fetch_stock, 'User')
    [System.Environment]::SetEnvironmentVariable('DETAIL_FETCH_DELAY', $fetch_delay, 'User')

    Write-Host "`n[SUCCESS] Saved to Windows Registry!" -ForegroundColor Green
    Write-Host "IMPORTANT: Please restart VS Code to apply these changes." -ForegroundColor Yellow
}
else {
    # --- Option 2: .env ---
    $envContent = @"
# Telegram Configuration
TELEGRAM_BOT_TOKEN=$token
TELEGRAM_CHAT_IDS_FULL=$chat_ids_full
TELEGRAM_CHAT_IDS_CHANGES_ONLY=$chat_ids_changes

# Thresholds
MIN_CAPACITY_AH=$min_cap
PRICE_ALERT_THRESHOLD=$threshold

# Delivery Date & Stock Settings
FETCH_DELIVERY_DATES=$fetch_dates
FETCH_REAL_STOCK=$fetch_stock
DETAIL_FETCH_DELAY=$fetch_delay

# Monitor URL
NKON_URL=https://www.nkon.nl/ua/rechargeable/lifepo4/prismatisch.html
"@
    $envContent | Out-File -FilePath ".env" -Encoding utf8
    Write-Host "`n[SUCCESS] Saved to .env file!" -ForegroundColor Green
    Write-Host "Changes will be applied immediately." -ForegroundColor Gray
}

# Always set process scope for immediate use in the same shell
$env:TELEGRAM_BOT_TOKEN = $token
$env:TELEGRAM_CHAT_IDS_FULL = $chat_ids_full
$env:TELEGRAM_CHAT_IDS_CHANGES_ONLY = $chat_ids_changes
$env:MIN_CAPACITY_AH = $min_cap
$env:PRICE_ALERT_THRESHOLD = $threshold
$env:FETCH_DELIVERY_DATES = $fetch_dates
$env:FETCH_REAL_STOCK = $fetch_stock
$env:DETAIL_FETCH_DELAY = $fetch_delay
