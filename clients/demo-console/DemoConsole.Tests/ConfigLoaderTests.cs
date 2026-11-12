using DemoConsole.Configuration;
using Xunit;

namespace DemoConsole.Tests;

public class ConfigLoaderTests
{
    [Fact]
    public void Loads_the_settings_with_defaults_and_the_secrets_from_the_repository()
    {
        using var repo = new TestRepo();

        var loaded = ConfigLoader.Load(repo.Root, repo.SettingsFile);

        Assert.Equal("RTS_DB_DEMO", loaded.Config.Database);
        Assert.Equal(3, loaded.Config.RefreshSeconds);
        Assert.Equal("127.0.0.1,14333", loaded.Config.SqlServer);
        Assert.Equal(3, loaded.Config.Stores.Count);
        Assert.Equal("Secret!123", loaded.SqlPassword);
        Assert.Equal("ta", loaded.Tokens["admin"]);
        Assert.Equal(Path.Combine(repo.Root, ".certs", "ca.crt"), loaded.Paths.CaCertificate);
        Assert.Empty(loaded.Problems);
    }

    [Fact]
    public void The_committed_appsettings_is_valid_and_points_at_the_demo_database()
    {
        var committed = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "appsettings.json"));
        using var repo = new TestRepo(File.ReadAllText(committed));

        var loaded = ConfigLoader.Load(repo.Root, repo.SettingsFile);

        Assert.Equal("RTS_DB_DEMO", loaded.Config.Database);
        Assert.Equal(3, loaded.Config.RefreshSeconds);
        Assert.Equal("https://localhost:8443/api/v1", loaded.Config.MiddlewareBaseUrl);
        Assert.Equal("https://localhost:9000/api/v1", loaded.Config.HqBaseUrl);
        Assert.Equal(new[] { "staff_dn1", "staff_dn2", "staff_dn3" }, loaded.Config.Stores.Select(s => s.Token));
    }

    [Theory]
    [InlineData("RTS_DB")]
    [InlineData("RTS_DB_TEST")]
    [InlineData("rts_db")]
    [InlineData("Rts_Db_Test")]
    public void Refuses_the_development_databases(string database)
    {
        using var repo = new TestRepo(TestRepo.DefaultSettings(database));

        var error = Assert.Throws<ConfigurationException>(() => ConfigLoader.Load(repo.Root, repo.SettingsFile));

        Assert.Contains("development database", error.Message);
    }

    [Fact]
    public void A_local_override_cannot_switch_to_RTS_DB()
    {
        using var repo = new TestRepo();
        File.WriteAllText(Path.Combine(repo.Root, "appsettings.Local.json"), """{ "Database": "RTS_DB" }""");

        Assert.Throws<ConfigurationException>(() => ConfigLoader.Load(repo.Root, repo.SettingsFile));
    }

    [Fact]
    public void A_local_override_changes_the_urls_for_another_machine()
    {
        using var repo = new TestRepo();
        File.WriteAllText(Path.Combine(repo.Root, "appsettings.Local.json"),
            """{ "MiddlewareBaseUrl": "https://192.168.1.10:8443/api/v1", "RefreshSeconds": 5 }""");

        var loaded = ConfigLoader.Load(repo.Root, repo.SettingsFile);

        Assert.Equal("https://192.168.1.10:8443/api/v1", loaded.Config.MiddlewareBaseUrl);
        Assert.Equal(5, loaded.Config.RefreshSeconds);
        Assert.Equal(3, loaded.Config.Stores.Count);
    }

    [Theory]
    [InlineData("RTS_DB_DEMO; DROP DATABASE RTS_DB")]
    [InlineData("RTS DB")]
    [InlineData("")]
    public void Refuses_a_database_name_that_is_not_a_plain_identifier(string database)
    {
        Assert.Throws<ConfigurationException>(() => ConfigLoader.CheckDatabaseName(database));
    }

    [Fact]
    public void Accepts_another_demo_database()
    {
        ConfigLoader.CheckDatabaseName("RTS_DB_DEMO2");
    }

    [Fact]
    public void Refuses_plain_http()
    {
        using var repo = new TestRepo(TestRepo.DefaultSettings().Replace("https://localhost:9000", "http://localhost:9000"));

        var error = Assert.Throws<ConfigurationException>(() => ConfigLoader.Load(repo.Root, repo.SettingsFile));

        Assert.Contains("HqBaseUrl", error.Message);
    }

    [Theory]
    [InlineData("\"RefreshSeconds\": 0,")]
    [InlineData("\"RefreshSeconds\": 301,")]
    [InlineData("\"FontSize\": 4,")]
    public void Refuses_values_out_of_range(string extra)
    {
        using var repo = new TestRepo(TestRepo.DefaultSettings(extra: extra));

        Assert.Throws<ConfigurationException>(() => ConfigLoader.Load(repo.Root, repo.SettingsFile));
    }

    [Fact]
    public void Missing_tokens_password_and_ca_are_listed_as_problems()
    {
        using var repo = new TestRepo(env: "DB_NAME=RTS_DB_DEMO\n", tokens: """{ "admin": "ta" }""", withCa: false);

        var loaded = ConfigLoader.Load(repo.Root, repo.SettingsFile);

        Assert.Contains(loaded.Problems, p => p.Contains("ca.crt"));
        Assert.Contains(loaded.Problems, p => p.Contains("'auditor'"));
        Assert.Contains(loaded.Problems, p => p.Contains("'hq_operator'"));
        Assert.Contains(loaded.Problems, p => p.Contains("'staff_dn2'"));
        Assert.Contains(loaded.Problems, p => p.Contains("MSSQL_SA_PASSWORD"));
        Assert.DoesNotContain(loaded.Problems, p => p.Contains("'admin'"));
        Assert.Equal(string.Empty, loaded.SqlPassword);
    }

    [Fact]
    public void Invalid_json_is_a_configuration_error()
    {
        using var repo = new TestRepo("{ not json");

        Assert.Throws<ConfigurationException>(() => ConfigLoader.Load(repo.Root, repo.SettingsFile));
    }
}
