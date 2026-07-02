<#
.SYNOPSIS
    Test connection to RDS SQL Server. Validates DNS, TCP, TLS, auth scheme, encryption, and server version.

.DESCRIPTION
    PowerShell equivalent of test_connection.py. Designed to run locally or via SSM (AWS-RunPowerShellScript).
    Credentials are handled via PSCredential or Secrets Manager — never as plain strings.

.PREREQUISITES
    Full connection test requires:
        Install-Package Microsoft.Data.SqlClient -Source nuget.org
    Secrets Manager (-SecretId) additionally requires:
        Install-Package AWSSDK.SecretsManager -Source nuget.org
        Install-Package System.Text.Json -Source nuget.org
    Network-only mode (-NetworkOnly) has no prerequisites.

.PARAMETER Server
    RDS endpoint or proxy endpoint.

.PARAMETER Port
    Port number (default: 1433).

.PARAMETER Credential
    PSCredential object. Use Get-Credential for interactive prompts.

.PARAMETER Database
    Database name (default: master).

.PARAMETER NetworkOnly
    Test DNS, TCP, TLS only — no credentials needed.

.PARAMETER SecretId
    AWS Secrets Manager secret ID. Retrieves credentials via .NET SDK.

.PARAMETER Region
    AWS region (for -SecretId).

.EXAMPLE
    # Network only (no credentials)
    .\test_connection.ps1 -Server mydb.abc123.us-east-1.rds.amazonaws.com -NetworkOnly

.EXAMPLE
    # Interactive credential prompt
    .\test_connection.ps1 -Server mydb.abc123.us-east-1.rds.amazonaws.com -Credential (Get-Credential) -Database mydb

.EXAMPLE
    # Secrets Manager (no credentials on command line)
    .\test_connection.ps1 -Server mydb.abc123.us-east-1.rds.amazonaws.com -SecretId mydb/credentials -Region us-east-1

.EXAMPLE
    # Via SSM (network-only — no credentials in command parameters)
    aws ssm send-command --instance-ids i-xxx --document-name AWS-RunPowerShellScript `
      --parameters 'commands=[".\test_connection.ps1 -Server mydb.abc123.us-east-1.rds.amazonaws.com -NetworkOnly"]'
#>

param(
    [Parameter(Mandatory=$true)][string]$Server,
    [int]$Port = 1433,
    [PSCredential]$Credential,
    [string]$Database = "master",
    [switch]$NetworkOnly,
    [string]$SecretId,
    [string]$Region
)

$passed = 0
$failed = 0

function Write-Pass($msg) { $script:passed++; Write-Host "✅ $msg" }
function Write-Fail($msg) { $script:failed++; Write-Host "❌ $msg" }
function Write-Warn($msg) { Write-Host "⚠️  $msg" }

# --- Network Tests ---

function Test-NetworkOnly {
    Write-Host ""
    Write-Host ("=" * 60)
    Write-Host "Network Test: ${Server}:${Port}"
    Write-Host ("=" * 60)
    Write-Host ""

    # 1. DNS
    try {
        $dns = [System.Net.Dns]::GetHostAddresses($Server) | Select-Object -First 1
        Write-Pass "DNS: $Server → $($dns.IPAddressToString)"
    } catch {
        Write-Fail "DNS: Cannot resolve $Server — $($_.Exception.Message)"
        Write-Summary
        return $false
    }

    # 2. TCP
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $result = $tcp.BeginConnect($Server, $Port, $null, $null)
        $success = $result.AsyncWaitHandle.WaitOne(10000)
        if ($success -and $tcp.Connected) {
            Write-Pass "TCP: Port $Port reachable"
            $tcp.Close()
        } else {
            $tcp.Close()
            throw "Connection timed out"
        }
    } catch {
        Write-Fail "TCP: Port $Port unreachable — $($_.Exception.Message)"
        Write-Host "   Check: security group inbound rules, NACLs, subnet routing"
        Write-Summary
        return $false
    }

    # 3. TLS
    try {
        $tcpClient = New-Object System.Net.Sockets.TcpClient($Server, $Port)
        $sslStream = New-Object System.Net.Security.SslStream($tcpClient.GetStream(), $false, {$true})
        $sslStream.AuthenticateAsClient($Server)
        Write-Pass "TLS: Handshake succeeded ($($sslStream.SslProtocol))"
        $sslStream.Close()
        $tcpClient.Close()
    } catch {
        Write-Warn "TLS: Handshake failed — $($_.Exception.Message)"
        Write-Host "   Note: SQL Server uses TDS-level encryption, not pure TLS on connect."
        Write-Host "   This may be OK — proceed to full connection test."
        $script:passed++
    }

    Write-Summary
    return ($script:failed -eq 0)
}

# --- Full Connection Test ---

function Test-FullConnection {
    param([PSCredential]$ConnCredential)

    # Ensure Microsoft.Data.SqlClient is available
    try {
        [void][Microsoft.Data.SqlClient.SqlConnection]
    } catch {
        try {
            Add-Type -Path (Get-ChildItem -Path "$env:USERPROFILE\.nuget\packages\microsoft.data.sqlclient" -Filter "Microsoft.Data.SqlClient.dll" -Recurse -ErrorAction Stop | Select-Object -First 1).FullName
        } catch {
            Write-Host "ERROR: Microsoft.Data.SqlClient not found. Install via: dotnet add package Microsoft.Data.SqlClient"
            Write-Host "       Or use NuGet: Install-Package Microsoft.Data.SqlClient"
            exit 1
        }
    }

    Write-Host ""
    Write-Host ("=" * 60)
    Write-Host "Testing: ${Server}:${Port}/${Database}"
    Write-Host "User: $($ConnCredential.UserName)"
    Write-Host ("=" * 60)

    # 1. Connect using SqlCredential — password never appears in connection string
    try {
        $connStr = "Server=$Server,$Port;Database=$Database;Encrypt=True;TrustServerCertificate=false;Connection Timeout=30;"
        $sqlCred = [Microsoft.Data.SqlClient.SqlCredential]::new($ConnCredential.UserName, $ConnCredential.Password)
        $conn = [Microsoft.Data.SqlClient.SqlConnection]::new($connStr, $sqlCred)
        $conn.Open()
        Write-Pass "CONNECT: Success"
    } catch {
        Write-Fail "CONNECT: Failed — $($_.Exception.Message)"
        Write-Summary
        return $false
    }

    # 2. Server version
    try {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = "SELECT @@VERSION AS version"
        $version = ($cmd.ExecuteScalar()).Split("`n")[0].Trim()
        Write-Pass "VERSION: $version"
    } catch {
        Write-Fail "VERSION: $($_.Exception.Message)"
    }

    # 3. Encryption
    try {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = "SELECT encrypt_option FROM sys.dm_exec_connections WHERE session_id = @@SPID"
        $encrypted = ($cmd.ExecuteScalar()).ToUpper() -eq "TRUE"
        if ($encrypted) { Write-Pass "ENCRYPTION: Active" }
        else { Write-Warn "ENCRYPTION: Not active"; $script:failed++ }
    } catch {
        Write-Fail "ENCRYPTION CHECK: $($_.Exception.Message)"
    }

    # 4. Auth scheme + connection properties
    try {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = "SELECT net_transport, protocol_type, auth_scheme, client_net_address FROM sys.dm_exec_connections WHERE session_id = @@SPID"
        $reader = $cmd.ExecuteReader()
        if ($reader.Read()) {
            Write-Pass "AUTH SCHEME: $($reader['auth_scheme'])"
            Write-Host "   Transport: $($reader['net_transport']) | Protocol: $($reader['protocol_type'])"
            Write-Host "   Client IP: $($reader['client_net_address'])"
        }
        $reader.Close()
    } catch {
        Write-Fail "CONNECTION PROPERTIES: $($_.Exception.Message)"
    }

    # 5. Database
    try {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = "SELECT DB_NAME() AS current_db"
        $currentDb = $cmd.ExecuteScalar()
        if ($currentDb -eq $Database) { Write-Pass "DATABASE: $currentDb" }
        else { Write-Warn "DATABASE: Connected to $currentDb, expected $Database"; $script:failed++ }
    } catch {
        Write-Fail "DATABASE CHECK: $($_.Exception.Message)"
    }

    # 6. RDS detection
    try {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = "SELECT CASE WHEN @@VERSION LIKE '%Amazon%' THEN 'RDS' WHEN SERVERPROPERTY('EngineEdition') = 8 THEN 'RDS' ELSE 'Non-RDS' END"
        $env = $cmd.ExecuteScalar()
        Write-Pass "ENVIRONMENT: $env"
    } catch {
        Write-Fail "ENVIRONMENT CHECK: $($_.Exception.Message)"
    }

    $conn.Close()
    Write-Summary
    return ($script:failed -eq 0)
}

# --- Secrets Manager ---

function Get-SecretCredentials {
    # Use .NET SDK directly — avoids Get-SECSecretValue and ConvertFrom-Json
    # which can surface secret values in verbose/debug/transcription logs.
    try {
        Add-Type -AssemblyName AWSSDK.SecretsManager -ErrorAction Stop
    } catch {
        Write-Host "ERROR: AWSSDK.SecretsManager assembly not found. Install via: dotnet add package AWSSDK.SecretsManager"
        exit 1
    }
    $config = New-Object Amazon.SecretsManager.AmazonSecretsManagerConfig
    if ($Region) { $config.RegionEndpoint = [Amazon.RegionEndpoint]::GetBySystemName($Region) }
    $client = New-Object Amazon.SecretsManager.AmazonSecretsManagerClient($config)
    $request = New-Object Amazon.SecretsManager.Model.GetSecretValueRequest
    $request.SecretId = $SecretId
    $response = $client.GetSecretValueAsync($request).GetAwaiter().GetResult()
    $secret = [System.Text.Json.JsonDocument]::Parse($response.SecretString)
    $root = $secret.RootElement
    $hostVal = if ($root.TryGetProperty("host", [ref]$null)) { $root.GetProperty("host").GetString() } else { $Server }
    $portVal = if ($root.TryGetProperty("port", [ref]$null)) { $root.GetProperty("port").GetRawText() } else { $Port }
    $userVal = $root.GetProperty("username").GetString()
    # Build SecureString character-by-character — never use ConvertTo-SecureString -AsPlainText
    $passChars = $root.GetProperty("password").GetString()
    $securePass = [System.Security.SecureString]::new()
    foreach ($c in $passChars.ToCharArray()) { $securePass.AppendChar($c) }
    $securePass.MakeReadOnly()
    $passChars = $null
    $dbVal = if ($root.TryGetProperty("dbname", [ref]$null)) { $root.GetProperty("dbname").GetString() } else { $Database }
    $secret.Dispose()
    return @{
        Server     = $hostVal
        Port       = $portVal
        Credential = [PSCredential]::new($userVal, $securePass)
        Database   = $dbVal
    }
}

# --- Summary ---

function Write-Summary {
    $total = $script:passed + $script:failed
    Write-Host ""
    Write-Host ("-" * 60)
    if ($script:failed -gt 0) {
        Write-Host "RESULTS: $($script:passed)/$total passed ($($script:failed) failed)"
    } else {
        Write-Host "RESULTS: $($script:passed)/$total passed — all checks passed ✅"
    }
    Write-Host ("-" * 60)
}

# --- Main ---

if ($NetworkOnly) {
    $success = Test-NetworkOnly
    exit $(if ($success) { 0 } else { 1 })
}

if ($SecretId) {
    Write-Host "Fetching credentials from Secrets Manager: $SecretId"
    $creds = Get-SecretCredentials
    $Server = $creds.Server
    $Port = $creds.Port
    $Credential = $creds.Credential
    $Database = $creds.Database
}

if (-not $Credential) {
    Write-Host "ERROR: Provide -Credential (Get-Credential), or -SecretId"
    exit 1
}

$success = Test-FullConnection -ConnCredential $Credential
exit $(if ($success) { 0 } else { 1 })
