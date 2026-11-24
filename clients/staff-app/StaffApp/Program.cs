using StaffApp.Configuration;
using StaffApp.Security;
using StaffApp.Services;
using StaffApp.UI;

namespace StaffApp;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, args) => ShowError(args.Exception.Message);
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
            ShowError((args.ExceptionObject as Exception)?.Message ?? "Lỗi không xác định");

        LoadedConfig config;
        System.Security.Cryptography.X509Certificates.X509Certificate2 authority;
        try
        {
            config = ConfigLoader.Load(AppContext.BaseDirectory);
            authority = ServerCertificateValidator.LoadAuthority(config.CaCertificatePath);
        }
        catch (ConfigurationException error)
        {
            ShowError(error.Message);
            return;
        }

        using (authority)
        using (var api = new StaffApiClient(config.Settings.BaseUrl, authority, config.Token))
        {
            Application.Run(new MainForm(config, api));
        }
    }

    private static void ShowError(string message) =>
        MessageBox.Show(message, "RetailSync Staff App", MessageBoxButtons.OK, MessageBoxIcon.Error);
}
