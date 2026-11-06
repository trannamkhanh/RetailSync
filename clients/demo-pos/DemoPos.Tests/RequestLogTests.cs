using System.Text;
using System.Text.Json;
using DemoPos.Models;
using DemoPos.Security;
using Xunit;

namespace DemoPos.Tests;

public sealed class RequestLogTests
{
    [Fact]
    public void KeepsTheLastTwoHundredEntriesNewestFirst()
    {
        var log = new RequestLog();
        for (var index = 0; index < 205; index++)
        {
            log.Add(new RequestLogEntry
            {
                Method = "POST",
                Url = $"https://localhost:9443/api/v1/pos/events?{index}",
                Status = 200,
                Kind = RequestKind.Pos,
            });
        }

        var entries = log.Snapshot();
        Assert.Equal(RequestLog.Capacity, entries.Count);
        Assert.Contains("?204", entries[0].Url);
        Assert.DoesNotContain(entries, entry => entry.Url.EndsWith("?4", StringComparison.Ordinal));
    }

    [Fact]
    public void DetailsNeverContainABearerToken()
    {
        const string token = "header.eyJzdWIiOiJwb3Nfc3lzdGVtIiwicm9sZSI6IlBPUyJ9.signature";
        var identity = JwtInspector.Describe(token);
        var entry = new RequestLogEntry
        {
            Method = "POST",
            Url = "https://localhost:9443/api/v1/pos/events",
            Status = 200,
            RequestBody = """{"event_type":"SALE"}""",
            ResponseBody = """{"outcome":"OK"}""",
            Role = identity.Role,
            Subject = identity.Subject,
            Kind = RequestKind.Pos,
        };

        Assert.Equal("POS", identity.Role);
        Assert.Equal("pos_system", identity.Subject);
        Assert.DoesNotContain(token, entry.DetailsText);
        Assert.DoesNotContain("Authorization", entry.DetailsText);
        Assert.Contains("POS / pos_system", entry.DetailsText);
    }

    [Fact]
    public void InvalidJwtPayloadDoesNotThrow()
    {
        var identity = JwtInspector.Describe("not-a-token");
        Assert.Equal(JwtIdentity.Unknown, identity);
    }
}

public sealed class JwtInspectorTests
{
    [Fact]
    public void ReadsRoleAndSubjectWithoutVerifyingTheSignature()
    {
        var payload = Base64Url(JsonSerializer.Serialize(new
        {
            sub = "staff_dn1",
            role = "Staff",
            store_id = "STORE-DN1",
        }));
        var identity = JwtInspector.Describe($"x.{payload}.signature");

        Assert.Equal("Staff", identity.Role);
        Assert.Equal("staff_dn1", identity.Subject);
    }

    private static string Base64Url(string value) =>
        Convert.ToBase64String(Encoding.UTF8.GetBytes(value))
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_');
}
