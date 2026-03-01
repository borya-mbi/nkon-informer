# Setup environment variables for NKON Monitor
# Choice between Windows Registry (Persistent) or .env file (Immediate/Portable)

Write-Host "--- NKON Monitor Setup ---" -ForegroundColor Cyan

# Helper to read from existing .env if present
function Get-CurrentFromEnv {
    param ([string]$Key)
    if (Test-Path ".env") {
        # Read entire file to handle multi-line quoted values
        $content = Get-Content ".env" -Raw
        # Match Key='value' where value can span multiple lines (non-greedy match)
        if ($content -match "(?m)^$Key='(?<value>[\s\S]*?)'(?:\r?\n|$)") {
            return $Matches['value']
        }
        
        # Fallback to simple line-based parsing for unquoted or simple values
        $line = Get-Content ".env" | Where-Object { $_ -match "^$Key=" }
        if ($line) {
            $val = $line.Split('=', 2)[1].Trim()
            if ($val.StartsWith('"') -and $val.EndsWith('"')) {
                $val = $val.Substring(1, $val.Length - 2)
            }
            return $val
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

# Step 2: Configuration for Scraper
$min_cap = Read-UserVariable -Name "MIN_CAPACITY_AH" -PromptText "Enter Global MIN_CAPACITY_AH" -DefaultValue "200"
$threshold = Read-UserVariable -Name "PRICE_ALERT_THRESHOLD" -PromptText "Enter PRICE_ALERT_THRESHOLD" -DefaultValue "5"
$fetch_dates = Read-UserVariable -Name "FETCH_DELIVERY_DATES" -PromptText "Fetch Delivery Dates for Pre-orders? (true/false)" -DefaultValue "true"
$fetch_stock = Read-UserVariable -Name "FETCH_REAL_STOCK" -PromptText "Probe Real Stock Quantity? (true/false)" -DefaultValue "true"
$small_threshold = Read-UserVariable -Name "SMALL_RESTOCK_THRESHOLD" -PromptText "Enter SMALL_RESTOCK_THRESHOLD (ignore notifications if <= X pcs)" -DefaultValue "16"
$fetch_delay = Read-UserVariable -Name "DETAIL_FETCH_DELAY" -PromptText "Delay between detail requests (seconds)" -DefaultValue "2"
$quiet_start = Read-UserVariable -Name "QUIET_HOURS_START" -PromptText "Quiet hours START (hour 0-23)" -DefaultValue "21"
$quiet_end = Read-UserVariable -Name "QUIET_HOURS_END" -PromptText "Quiet hours END (hour 0-23)" -DefaultValue "8"
$generate_graphs = Read-UserVariable -Name "GENERATE_GRAPHS" -PromptText "Generate History Graphs? (true/false)" -DefaultValue "true"

Write-Host "`nStep 3: Granular Recipients Wizard" -ForegroundColor Yellow
$current_json = Get-CurrentFromEnv -Key "TELEGRAM_CONFIG_JSON"
if ([string]::IsNullOrWhiteSpace($current_json)) {
    $current_json = [System.Environment]::GetEnvironmentVariable("TELEGRAM_CONFIG_JSON", 'User')
}

$recipients = @()
if (-not [string]::IsNullOrWhiteSpace($current_json)) {
    try {
        $recipients = $current_json | ConvertFrom-Json
        Write-Host "Found $($recipients.Count) existing recipients." -ForegroundColor Gray
    }
    catch {
        Write-Host "Warning: Could not parse existing TELEGRAM_CONFIG_JSON" -ForegroundColor DarkYellow
    }
}

$manageRecipients = Read-Host "Manage recipients? (y = start wizard, n/Enter = keep current)"
if ($manageRecipients -eq "y") {
    $mode = Read-Host "  (a) Append to existing or (r) Reset and start new? [default: a]"
    if ([string]::IsNullOrWhiteSpace($mode)) { $mode = "a" }

    $newRecipients = @()
    if ($mode -eq "a") {
        $newRecipients = $recipients
        Write-Host "  Continuing with $($newRecipients.Count) existing recipients." -ForegroundColor Gray
    }

    $done = $false
    while (-not $done) {
        Write-Host "`n--- Adding Recipient ---" -ForegroundColor Gray
        $chatId = Read-Host "  Chat ID (required, use -100xxx for channels/groups)"
        if ([string]::IsNullOrWhiteSpace($chatId)) { 
            if ($newRecipients.Count -eq 0) { Write-Host "Chat ID is required!" -ForegroundColor Red; continue }
            else { break }
        }
        
        $type = Read-Host "  Report Type (full/changes, default: changes)"
        if ([string]::IsNullOrWhiteSpace($type)) { $type = "changes" }
        
        $thread = Read-Host "  Thread ID (optional topic ID, Enter to skip)"
        $recMinAh = Read-Host "  Custom Min Ah (default: $min_cap)"
        if ([string]::IsNullOrWhiteSpace($recMinAh)) { $recMinAh = [int]$min_cap } else { $recMinAh = [int]$recMinAh }
        
        $url = Read-Host "  Header Link URL (mandatory for first recipient, Enter to skip for others)"
        if ([string]::IsNullOrWhiteSpace($url) -and $newRecipients.Count -eq 0) {
            Write-Host "  Error: Header Link URL is required for the first recipient!" -ForegroundColor Red
            continue
        }
        
        $name = Read-Host "  Name for footer (optional, e.g. Канал)"
        
        $recipientProps = [ordered]@{
            chat_id         = $chatId
            type            = $type
            min_capacity_ah = $recMinAh
        }
        if (-not [string]::IsNullOrWhiteSpace($thread)) { $recipientProps['thread_id'] = [int]$thread }
        if (-not [string]::IsNullOrWhiteSpace($url)) { $recipientProps['url'] = $url }
        if (-not [string]::IsNullOrWhiteSpace($name)) { $recipientProps['name'] = $name }
        
        $recipient = [PSCustomObject]$recipientProps
        
        $newRecipients += $recipient
        
        $another = Read-Host "Add another recipient? (y/n, default: n)"
        if ($another -ne "y") { $done = $true }
    }
    if ($newRecipients.Count -gt 0) {
        $recipients = $newRecipients
    }
}

$final_json = ConvertTo-Json -InputObject @($recipients) -Depth 10

if ($storageChoice -eq "1") {
    # --- Option 1: Registry ---
    [System.Environment]::SetEnvironmentVariable('TELEGRAM_BOT_TOKEN', $token, 'User')
    [System.Environment]::SetEnvironmentVariable('TELEGRAM_CONFIG_JSON', $final_json, 'User')
    [System.Environment]::SetEnvironmentVariable('MIN_CAPACITY_AH', $min_cap, 'User')
    [System.Environment]::SetEnvironmentVariable('PRICE_ALERT_THRESHOLD', $threshold, 'User')
    [System.Environment]::SetEnvironmentVariable('FETCH_DELIVERY_DATES', $fetch_dates, 'User')
    [System.Environment]::SetEnvironmentVariable('FETCH_REAL_STOCK', $fetch_stock, 'User')
    [System.Environment]::SetEnvironmentVariable('SMALL_RESTOCK_THRESHOLD', $small_threshold, 'User')
    [System.Environment]::SetEnvironmentVariable('DETAIL_FETCH_DELAY', $fetch_delay, 'User')
    [System.Environment]::SetEnvironmentVariable('QUIET_HOURS_START', $quiet_start, 'User')
    [System.Environment]::SetEnvironmentVariable('QUIET_HOURS_END', $quiet_end, 'User')
    [System.Environment]::SetEnvironmentVariable('GENERATE_GRAPHS', $generate_graphs, 'User')

    Write-Host "`n[SUCCESS] Settings saved to Windows Registry!" -ForegroundColor Green
    Write-Host "IMPORTANT: Restart VS Code or terminal to apply." -ForegroundColor Yellow
}
else {
    # --- Option 2: .env ---
    $envContent = @"
# Telegram Configuration
TELEGRAM_BOT_TOKEN=$token
TELEGRAM_CONFIG_JSON='$final_json'

# Scraper Thresholds
MIN_CAPACITY_AH=$min_cap
PRICE_ALERT_THRESHOLD=$threshold
SMALL_RESTOCK_THRESHOLD=$small_threshold

# Quiet Mode
QUIET_HOURS_START=$quiet_start
QUIET_HOURS_END=$quiet_end

# Delivery Date & Stock Settings
FETCH_DELIVERY_DATES=$fetch_dates
FETCH_REAL_STOCK=$fetch_stock
DETAIL_FETCH_DELAY=$fetch_delay
GENERATE_GRAPHS=$generate_graphs

# Monitor URL
NKON_URL=https://www.nkon.nl/ua/rechargeable/lifepo4/prismatisch.html
"@
    $envContent | Out-File -FilePath ".env" -Encoding utf8
    Write-Host "`n[SUCCESS] Saved to .env file!" -ForegroundColor Green
}

# Apply to current session
$env:TELEGRAM_BOT_TOKEN = $token
$env:TELEGRAM_CONFIG_JSON = $final_json
$env:MIN_CAPACITY_AH = $min_cap
$env:PRICE_ALERT_THRESHOLD = $threshold
$env:FETCH_DELIVERY_DATES = $fetch_dates
$env:FETCH_REAL_STOCK = $fetch_stock
$env:SMALL_RESTOCK_THRESHOLD = $small_threshold
$env:DETAIL_FETCH_DELAY = $fetch_delay
$env:QUIET_HOURS_START = $quiet_start
$env:QUIET_HOURS_END = $quiet_end
$env:GENERATE_GRAPHS = $generate_graphs
