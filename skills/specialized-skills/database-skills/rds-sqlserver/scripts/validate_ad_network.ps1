<#
.SYNOPSIS
    Validates network connectivity and AD prerequisites for RDS SQL Server Windows Authentication.
    Run from an EC2 instance in the same VPC/subnets where you plan to launch the RDS instance.

.PARAMETER Region
    AWS region (e.g., us-east-1)

.PARAMETER DomainFQDN
    Fully qualified domain name of your AD (e.g., corp.example.com)

.USAGE
    .\validate_ad_network.ps1 -Region 'us-east-1' -DomainFQDN 'corp.example.com'
#>

param(
    [Parameter(Mandatory=$true)][string]$Region,
    [Parameter(Mandatory=$true)][string]$DomainFQDN
)

function Test-DomainPorts {
    param (
        [string]$Domain,
        [array]$Ports
    )
    foreach ($portInfo in $Ports) {
        try {
            $conn = New-Object System.Net.Sockets.TcpClient
            $connectionResult = $conn.BeginConnect($Domain, $portInfo.Port, $null, $null)
            $success = $connectionResult.AsyncWaitHandle.WaitOne(1000)
            if ($success) {
                $conn.EndConnect($connectionResult)
                $result = $true
            } else {
                $result = $false
            }
        }
        catch {
            $result = $false
        }
        finally {
            if ($null -ne $conn) { $conn.Close() }
        }
        Write-Host "$($portInfo.Description) (port $($portInfo.Port)): $result"
    }
}

function Test-DomainReachability {
    param ([string]$DomainName)
    try {
        $dnsResults = Resolve-DnsName -Name $DomainName -ErrorAction Stop
        Write-Host "Domain $DomainName resolves to: $($dnsResults.IpAddress)"
        return $true
    }
    catch {
        Write-Host "ERROR: Domain $DomainName DNS resolution failed: $($_.Exception.Message)"
        return $false
    }
}

# Required ports for AD authentication
$ports = @(
    @{Port = 53;   Description = "DNS"},
    @{Port = 88;   Description = "Kerberos"},
    @{Port = 389;  Description = "LDAP"},
    @{Port = 445;  Description = "SMB"},
    @{Port = 464;  Description = "Kerberos password change"},
    @{Port = 636;  Description = "LDAPS"},
    @{Port = 135;  Description = "DCE/EPMAP"},
    @{Port = 3268; Description = "Global Catalog"},
    @{Port = 3269; Description = "Global Catalog over SSL"},
    @{Port = 9389; Description = "AD DS"}
)

Write-Host "============================================"
Write-Host "RDS SQL Server AD Network Validation"
Write-Host "Region: $Region"
Write-Host "Domain: $DomainFQDN"
Write-Host "============================================"
Write-Host ""

# 1. Check domain membership
$domain = (Get-WmiObject Win32_ComputerSystem).Domain
if ($domain -eq 'WORKGROUP') {
    Write-Host "[WARN] Host $env:computername is NOT domain-joined (WORKGROUP)"
} else {
    Write-Host "[OK] Host $env:computername is joined to $domain"
}
Write-Host ""

# 2. DNS resolution
Write-Host "--- DNS Resolution ---"
$isReachable = Test-DomainReachability -DomainName $DomainFQDN
Write-Host ""

# 3. Port connectivity
if ($isReachable) {
    Write-Host "--- Port Connectivity ---"
    Test-DomainPorts -Domain $DomainFQDN -Ports $ports
} else {
    Write-Host "Port check skipped — domain not reachable"
}
Write-Host ""

# 4. DNS server settings
$networkConfig = Get-WmiObject Win32_NetworkAdapterConfiguration |
    Where-Object { $_.IPEnabled -eq $true } |
    Select-Object -First 1
$dnsServers = $networkConfig.DNSServerSearchOrder
Write-Host "--- DNS Servers ---"
if ($dnsServers) {
    foreach ($server in $dnsServers) { Write-Host "  $server" }
} else {
    Write-Host "  [WARN] No DNS servers configured"
}
Write-Host ""

# 5. AWS service endpoint reachability
$services = "s3", "ec2", "secretsmanager", "logs", "events", "monitoring", "ssm", "ec2messages", "ssmmessages"

Write-Host "--- AWS Service Endpoints ---"
foreach ($service in $services) {
    $endpoint = "${service}.${Region}.amazonaws.com"
    $tcp = New-Object Net.Sockets.TcpClient
    try {
        $connectTask = $tcp.ConnectAsync($endpoint, 443)
        $null = $connectTask.Wait(3000)
        $result = $tcp.Connected
    } catch {
        $result = $false
    }
    Write-Host "  $service : $result"
}
Write-Host ""
Write-Host "============================================"
Write-Host "Validation complete"
Write-Host "============================================"
