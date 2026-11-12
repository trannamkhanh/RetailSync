namespace DemoConsole.Tests;

/// <summary>A throwaway repository folder: compose.yaml, appsettings.json, .env, .tokens, .certs.</summary>
internal sealed class TestRepo : IDisposable
{
    public const string AllTokens = """
        {
          "staff_dn1": "t1", "staff_dn2": "t2", "staff_dn3": "t3",
          "admin": "ta", "auditor": "tu", "hq_operator": "th"
        }
        """;

    public TestRepo(string? settings = null, string? env = "MSSQL_SA_PASSWORD=Secret!123\n",
                    string? tokens = AllTokens, bool withCa = true)
    {
        Root = Path.Combine(Path.GetTempPath(), "demo-console-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Root);
        File.WriteAllText(Path.Combine(Root, "compose.yaml"), "name: test\n");
        SettingsFile = Path.Combine(Root, "appsettings.json");
        File.WriteAllText(SettingsFile, settings ?? DefaultSettings());
        if (env is not null)
        {
            File.WriteAllText(Path.Combine(Root, ".env"), env);
        }

        if (tokens is not null)
        {
            Directory.CreateDirectory(Path.Combine(Root, ".tokens"));
            File.WriteAllText(Path.Combine(Root, ".tokens", "demo_tokens.json"), tokens);
        }

        if (withCa)
        {
            Directory.CreateDirectory(Path.Combine(Root, ".certs"));
            File.WriteAllText(Path.Combine(Root, ".certs", "ca.crt"), "placeholder");
        }
    }

    public string Root { get; }

    public string SettingsFile { get; }

    public static string DefaultSettings(string database = "RTS_DB_DEMO", string extra = "") => $$"""
        {
          "MiddlewareBaseUrl": "https://localhost:8443/api/v1",
          "HqBaseUrl": "https://localhost:9000/api/v1",
          "Database": "{{database}}",
          {{extra}}
          "Stores": [
            { "StoreId": "STORE-DN1", "Name": "Hải Châu", "Token": "staff_dn1" },
            { "StoreId": "STORE-DN2", "Name": "Thanh Khê", "Token": "staff_dn2" },
            { "StoreId": "STORE-DN3", "Name": "Sơn Trà", "Token": "staff_dn3" }
          ],
          "Products": [ { "Sku": "SKU-0001", "Name": "Fresh milk 1L" } ]
        }
        """;

    public void Dispose()
    {
        try
        {
            Directory.Delete(Root, recursive: true);
        }
        catch (IOException)
        {
        }
    }
}
