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
                    "RetailSync Bảng điều khiển demo — thiếu chứng chỉ", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            Application.Run(new MainForm(loaded));
        }
        catch (ConfigurationException error)
        {
            MessageBox.Show(error.Message, "RetailSync Bảng điều khiển demo — cấu hình chưa đúng",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        catch (Exception error)
        {
            MessageBox.Show(error.ToString(), "RetailSync Bảng điều khiển demo — lỗi khởi động",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
