# Setup environment variables for NKON Monitor
# These variables are stored in the Windows Registry for the current User
# No changes to system files or admin rights required.

Write-Host "--- NKON Monitor Setup ---" -ForegroundColor Cyan

function Read-UserVariable {
    param (
        [string]$Name,
        [string]$PromptText,
        [bool]$Required = $false,
        [string]$DefaultValue = ""
    )
    
    $current = [System.Environment]::GetEnvironmentVariable($Name, 'User')
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
        if (-not [string]::IsNullOrWhiteSpace($current)) {
            return $current
        }
        if (-not [string]::IsNullOrWhiteSpace($DefaultValue)) {
            return $DefaultValue
        }
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

$token = Read-UserVariable -Name "TELEGRAM_BOT_TOKEN" -PromptText "Enter TELEGRAM_BOT_TOKEN" -Required $true

# Legacy cleanup (Removing legacy variable prompts, only granular)
Write-Host "Configuration for Notifications:" -ForegroundColor Yellow
$chat_ids_full = Read-UserVariable -Name "TELEGRAM_CHAT_IDS_FULL" -PromptText "Enter Chat IDs for FULL Reports (comma separated)"
$chat_ids_changes = Read-UserVariable -Name "TELEGRAM_CHAT_IDS_CHANGES_ONLY" -PromptText "Enter Chat IDs for CHANGES ONLY (comma separated)"

# Logic: Remove Changes IDs from Full IDs to avoid duplicates
if (-not [string]::IsNullOrWhiteSpace($chat_ids_full) -and -not [string]::IsNullOrWhiteSpace($chat_ids_changes)) {
    $full_list = $chat_ids_full -split ',' | ForEach-Object { $_.Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $changes_list = $chat_ids_changes -split ',' | ForEach-Object { $_.Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    
    # Filter full list
    $new_full_list = @()
    foreach ($id in $full_list) {
        if ($changes_list -notcontains $id) {
            $new_full_list += $id
        }
        else {
            Write-Host "Notice: ID $id removed from FULL list because it is in CHANGES ONLY list." -ForegroundColor Gray
        }
    }
    
    $chat_ids_full = $new_full_list -join ','
}

$min_cap = Read-UserVariable -Name "MIN_CAPACITY_AH" -PromptText "Enter MIN_CAPACITY_AH" -DefaultValue "200"
$threshold = Read-UserVariable -Name "PRICE_ALERT_THRESHOLD" -PromptText "Enter PRICE_ALERT_THRESHOLD" -DefaultValue "5"

# Set Environment Variables (User Scope - Persistent)
[System.Environment]::SetEnvironmentVariable('TELEGRAM_BOT_TOKEN', $token, 'User')
[System.Environment]::SetEnvironmentVariable('TELEGRAM_CHAT_IDS', $null, 'User') 
[System.Environment]::SetEnvironmentVariable('TELEGRAM_CHAT_IDS_FULL', $chat_ids_full, 'User')
[System.Environment]::SetEnvironmentVariable('TELEGRAM_CHAT_IDS_CHANGES_ONLY', $chat_ids_changes, 'User')
[System.Environment]::SetEnvironmentVariable('MIN_CAPACITY_AH', $min_cap, 'User')
[System.Environment]::SetEnvironmentVariable('PRICE_ALERT_THRESHOLD', $threshold, 'User')

# Set Environment Variables (Process Scope - Immediate for current session)
$env:TELEGRAM_BOT_TOKEN = $token
$env:TELEGRAM_CHAT_IDS = $null
$env:TELEGRAM_CHAT_IDS_FULL = $chat_ids_full
$env:TELEGRAM_CHAT_IDS_CHANGES_ONLY = $chat_ids_changes
$env:MIN_CAPACITY_AH = $min_cap
$env:PRICE_ALERT_THRESHOLD = $threshold

Write-Host "`n[SUCCESS] Environment variables saved!" -ForegroundColor Green
Write-Host "IMPORTANT: Please restart your terminal or VS Code for changes to take effect." -ForegroundColor Yellow
Write-Host "Legacy TELEGRAM_CHAT_IDS has been cleared." -ForegroundColor Gray
