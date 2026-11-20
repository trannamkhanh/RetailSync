using System.Text;
using StaffApp.Configuration;
using Xunit;

namespace StaffApp.Tests;

public sealed class ConfigLoaderTests : IDisposable
{
    private readonly string _folder = Path.Combine(Path.GetTempPath(), "staffapp-" + Guid.NewGuid().ToString("N"));

    public ConfigLoaderTests() => Directory.CreateDirectory(_folder);

    public void Dispose() => Directory.Delete(_folder, recursive: true);

    /// <summary>An unsigned JWT with these claims; the app never checks the signature.</summary>
    internal static string Token(string claims)
    {
        static string Encode(string json) =>
            Convert.ToBase64String(Encoding.UTF8.GetBytes(json)).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        return $"{Encode("""{"alg":"HS256","typ":"JWT"}""")}.{Encode(claims)}.signature";
    }

    private static readonly string StaffToken = Token("""{"sub":"staff_dn1","role":"Staff","store_id":"STORE-DN1","exp":4102444800}""");

    private void Write(string name, string text) => File.WriteAllText(Path.Combine(_folder, name), text);

    private void Settings() => Write("appsettings.json",
        """{"BaseUrl":"https://localhost:8443/api/v1","CaCertificatePath":"ca.crt","TokenFile":"staff_token.txt"}""");

    [Fact]
    public void Pb46_loads_settings_and_takes_the_store_from_the_token()
    {
        Settings();
        Write("staff_token.txt", StaffToken + "\r\n");

        var config = ConfigLoader.Load(_folder);

        Assert.Equal(StaffToken, config.Token);
        Assert.Equal(("staff_dn1", "STORE-DN1", "Staff"),
            (config.TokenInfo.Subject, config.TokenInfo.StoreId, config.TokenInfo.Role));
        Assert.Equal(Path.Combine(_folder, "ca.crt"), config.CaCertificatePath);
        Assert.Equal(12f, config.Settings.FontSize);
    }

    [Fact]
    public void Pb46_local_settings_override_only_their_keys()
    {
        Settings();
        Write("appsettings.Local.json", """{"BaseUrl":"https://192.168.1.10:8443/api/v1","FontSize":14}""");
        Write("staff_token.txt", StaffToken);

        var config = ConfigLoader.Load(_folder);

        Assert.Equal(("https://192.168.1.10:8443/api/v1", 14f, "ca.crt"),
            (config.Settings.BaseUrl, config.Settings.FontSize, config.Settings.CaCertificatePath));
    }

    [Fact]
    public void Pb46_reads_the_named_token_from_a_demo_tokens_file()
    {
        Write("appsettings.json",
            """{"BaseUrl":"https://localhost:8443/api/v1","TokenFile":"demo_tokens.json","TokenName":"staff_dn2"}""");
        var dn2 = Token("""{"sub":"staff_dn2","role":"Staff","store_id":"STORE-DN2"}""");
        Write("demo_tokens.json", $$"""{"admin":"{{Token("""{"sub":"admin","role":"Admin"}""")}}","staff_dn2":"{{dn2}}"}""");

        var config = ConfigLoader.Load(_folder);

        Assert.Equal(("staff_dn2", "STORE-DN2"), (config.TokenInfo.Subject, config.TokenInfo.StoreId));
    }

    [Fact]
    public void Pb46_missing_token_file_is_a_clear_error()
    {
        Settings();

        var error = Assert.Throws<ConfigurationException>(() => ConfigLoader.Load(_folder));

        Assert.Contains("Missing token file", error.Message);
    }

    [Fact]
    public void Pb46_token_without_a_store_is_refused()
    {
        Settings();
        Write("staff_token.txt", Token("""{"sub":"admin","role":"Admin"}"""));

        var error = Assert.Throws<ConfigurationException>(() => ConfigLoader.Load(_folder));

        Assert.Contains("staff_dn*", error.Message);
    }

    [Theory]
    [InlineData("""{"BaseUrl":"http://localhost:8443/api/v1"}""", "https")]
    [InlineData("""{"FontSize":40}""", "FontSize")]
    [InlineData("""{"BaseUrl":""", "not valid JSON")]
    public void Pb46_bad_settings_are_refused(string local, string expected)
    {
        Settings();
        Write("appsettings.Local.json", local);
        Write("staff_token.txt", StaffToken);

        var error = Assert.Throws<ConfigurationException>(() => ConfigLoader.Load(_folder));

        Assert.Contains(expected, error.Message);
    }

    [Fact]
    public void Stf46_5_token_expiry_is_read_from_the_exp_claim()
    {
        var expired = TokenInfo.Read(Token("""{"sub":"staff_dn1","store_id":"STORE-DN1","exp":1700000000}"""));

        Assert.True(expired.IsExpired(DateTimeOffset.UtcNow));
        Assert.False(TokenInfo.Read(StaffToken).IsExpired(DateTimeOffset.UtcNow));
    }

    [Fact]
    public void Pb46_a_value_that_is_not_a_jwt_is_refused()
    {
        Assert.Throws<ConfigurationException>(() => TokenInfo.Read("not-a-token"));
    }
}
