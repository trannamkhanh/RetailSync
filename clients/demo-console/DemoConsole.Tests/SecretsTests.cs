using DemoConsole.Configuration;
using DemoConsole.Services;
using Xunit;

namespace DemoConsole.Tests;

public class SecretsTests
{
    [Fact]
    public void Env_file_reads_values_and_skips_comments()
    {
        var values = EnvFile.Parse(new[]
        {
            "# comment",
            "MSSQL_SA_PASSWORD=\"Pa=ss word\"",
            "",
            "DB_NAME = RTS_DB_DEMO ",
            "not a line",
            "DB_NAME=RTS_DB_DEMO2",
        });

        Assert.Equal("Pa=ss word", values["MSSQL_SA_PASSWORD"]);
        Assert.Equal("RTS_DB_DEMO2", values["DB_NAME"]);
        Assert.Equal(2, values.Count);
    }

    [Fact]
    public void Missing_env_file_gives_no_values()
    {
        Assert.Empty(EnvFile.Read(Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"), ".env")));
    }

    [Fact]
    public void Token_file_is_read_by_name()
    {
        using var repo = new TestRepo();

        var tokens = TokenStore.Load(Path.Combine(repo.Root, ".tokens", "demo_tokens.json"));

        Assert.Equal("t2", tokens["staff_dn2"]);
        Assert.Equal("th", tokens["hq_operator"]);
        Assert.Equal(6, tokens.Count);
    }

    [Fact]
    public void Missing_token_file_gives_no_tokens()
    {
        Assert.Empty(TokenStore.Load(Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N") + ".json")));
    }

    [Fact]
    public void Token_file_that_is_not_json_is_a_configuration_error()
    {
        using var repo = new TestRepo(tokens: "{ broken");

        Assert.Throws<ConfigurationException>(() =>
            TokenStore.Load(Path.Combine(repo.Root, ".tokens", "demo_tokens.json")));
    }

    [Fact]
    public void Required_tokens_are_the_three_roles_and_one_staff_token_per_store()
    {
        using var repo = new TestRepo();
        var loaded = ConfigLoader.Load(repo.Root, repo.SettingsFile);

        var required = ConfigLoader.RequiredTokens(loaded.Config).ToList();

        Assert.Equal(new[] { "admin", "auditor", "hq_operator", "staff_dn1", "staff_dn2", "staff_dn3" }, required);
    }
}
