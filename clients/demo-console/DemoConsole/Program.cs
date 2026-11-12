using DemoConsole.Configuration;
using DemoConsole.UI;

namespace DemoConsole;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();

        try
        {
            var loaded = ConfigLoader.Load();
            if (!File.Exists(loaded.Paths.CaCertificate))
            {
                MessageBox.Show(string.Join("\n\n", loaded.Problems),
                    "RetailSync demo console - thiếu chứng chỉ", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            Application.Run(new MainForm(loaded));
        }
        catch (ConfigurationException error)
        {
            MessageBox.Show(error.Message, "RetailSync demo console - cấu hình chưa đúng",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        catch (Exception error)
        {
            MessageBox.Show(error.ToString(), "RetailSync demo console - lỗi khởi động",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
