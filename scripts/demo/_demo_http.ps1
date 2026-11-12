<#
.SYNOPSIS
    Shared helper of the demo scripts (PB-42-7). Dot-source it; do not run it.

.DESCRIPTION
    Invoke-DemoApi sends one HTTPS request that trusts only the development CA
    (.certs/ca.crt by default), with the bearer token named by -TokenName from
    .tokens/demo_tokens.json. It prints one line with the HTTP status, the error
    code and the body in short, and returns $true for a 2xx answer.

    Windows PowerShell 5.1 has no option to trust one extra CA, so the request is
    made by a small C# class: the server certificate must chain to that CA and
    match the host name. Tokens are never printed.
#>

$script:DemoRepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$script:DefaultTokensPath = Join-Path $script:DemoRepoRoot ".tokens\demo_tokens.json"
$script:DefaultCaPath = Join-Path $script:DemoRepoRoot ".certs\ca.crt"

if (-not ([System.Management.Automation.PSTypeName]'RtsDemoHttp').Type) {
    Add-Type -ReferencedAssemblies System.Net.Http -TypeDefinition @'
using System;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading.Tasks;

public sealed class RtsDemoHttpResult
{
    public int Status;
    public string Body;
    public string Error;
}

public static class RtsDemoHttp
{
    public static RtsDemoHttpResult Send(string method, string url, string token, string jsonBody,
                                         string caPath, int timeoutSeconds)
    {
        X509Certificate2 authority = new X509Certificate2(caPath);
        HttpClientHandler handler = new HttpClientHandler();
        handler.ServerCertificateCustomValidationCallback =
            delegate (HttpRequestMessage message, X509Certificate2 certificate, X509Chain chain, SslPolicyErrors errors)
            {
                return Validate(certificate, errors, authority);
            };
        RtsDemoHttpResult result = new RtsDemoHttpResult();
        using (HttpClient client = new HttpClient(handler))
        {
            client.Timeout = TimeSpan.FromSeconds(timeoutSeconds);
            HttpRequestMessage request = new HttpRequestMessage(new HttpMethod(method), url);
            request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
            if (!String.IsNullOrEmpty(token))
            {
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            }
            // PowerShell passes an absent string as "", so empty means no body.
            if (!String.IsNullOrEmpty(jsonBody))
            {
                request.Content = new StringContent(jsonBody, Encoding.UTF8, "application/json");
            }
            try
            {
                HttpResponseMessage response = client.SendAsync(request).GetAwaiter().GetResult();
                result.Status = (int)response.StatusCode;
                result.Body = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            }
            catch (Exception error)
            {
                Exception inner = error;
                while (inner.InnerException != null) { inner = inner.InnerException; }
                result.Status = 0;
                result.Body = "";
                result.Error = error is TaskCanceledException
                    ? "No answer within " + timeoutSeconds + " seconds."
                    : inner.Message;
            }
        }
        return result;
    }

    private static bool Validate(X509Certificate2 certificate, SslPolicyErrors errors, X509Certificate2 authority)
    {
        if (certificate == null) { return false; }
        if ((errors & SslPolicyErrors.RemoteCertificateNameMismatch) != 0) { return false; }
        using (X509Chain chain = new X509Chain())
        {
            chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
            chain.ChainPolicy.VerificationFlags = X509VerificationFlags.AllowUnknownCertificateAuthority;
            chain.ChainPolicy.ExtraStore.Add(authority);
            if (!chain.Build(certificate)) { return false; }
            X509Certificate2 root = chain.ChainElements[chain.ChainElements.Count - 1].Certificate;
            return String.Equals(root.Thumbprint, authority.Thumbprint, StringComparison.OrdinalIgnoreCase);
        }
    }
}
'@ -IgnoreWarnings -WarningAction SilentlyContinue
}

function Get-DemoToken {
    param([string]$TokenName, [string]$TokensPath)
    if ([string]::IsNullOrEmpty($TokenName)) { return $null }
    if (-not (Test-Path $TokensPath)) {
        throw "Missing $TokensPath. Run scripts/demo/reset_demo_db.ps1 on machine S, or copy the file from S."
    }
    $tokens = Get-Content -Raw -Encoding UTF8 $TokensPath | ConvertFrom-Json
    $value = $tokens.$TokenName
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "$TokensPath has no token named '$TokenName'."
    }
    return $value
}

function Format-DemoBody {
    param([string]$Body, [int]$Max = 400)
    if ($null -eq $Body) { return "" }
    $flat = ($Body -replace '\s+', ' ').Trim()
    if ($flat.Length -gt $Max) { return $flat.Substring(0, $Max) + " ..." }
    return $flat
}

function Get-DemoErrorCode {
    param([string]$Body)
    try {
        $json = $Body | ConvertFrom-Json -ErrorAction Stop
        if ($json.code) { return [string]$json.code }
    }
    catch { }
    return "-"
}

function Invoke-DemoApi {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Url,
        [string]$TokenName,
        [string]$Body,
        [string]$TokensPath = $script:DefaultTokensPath,
        [string]$CaPath = $script:DefaultCaPath,
        [int]$TimeoutSeconds = 30,
        [switch]$Quiet
    )
    if (-not (Test-Path $CaPath)) {
        throw "Missing CA certificate $CaPath. Copy .certs/ca.crt from machine S."
    }
    $token = Get-DemoToken -TokenName $TokenName -TokensPath $TokensPath
    $caFull = (Resolve-Path $CaPath).Path
    $result = [RtsDemoHttp]::Send($Method, $Url, $token, $Body, $caFull, $TimeoutSeconds)
    $who = if ($TokenName) { " as $TokenName" } else { "" }
    if (-not $Quiet) {
        Write-Host "$Method $Url$who"
        if ($result.Status -eq 0) {
            Write-Host "HTTP -   code: UNREACHABLE   $($result.Error)" -ForegroundColor Red
        }
        else {
            $code = Get-DemoErrorCode $result.Body
            $color = if ($result.Status -ge 200 -and $result.Status -lt 300) { "Green" } else { "Yellow" }
            Write-Host ("HTTP {0}   code: {1}   {2}" -f $result.Status, $code, (Format-DemoBody $result.Body)) -ForegroundColor $color
        }
    }
    return $result
}

function New-DemoCommonArgs {
    param([string]$TokensPath, [string]$CaPath)
    $common = @{}
    if ($TokensPath) { $common.TokensPath = $TokensPath }
    if ($CaPath) { $common.CaPath = $CaPath }
    return $common
}

function Exit-Demo {
    param($Result)
    if ($Result.Status -ge 200 -and $Result.Status -lt 300) { exit 0 }
    exit 1
}
