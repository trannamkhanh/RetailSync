using DemoPos.Configuration;
using DemoPos.UI;

namespace DemoPos;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();

        try
        {
            var loaded = ConfigLoader.Load();
            if (!loaded.Config.UseMock && loaded.Problems.Count > 0)
            {
                MessageBox.Show(
                    string.Join("\n\n", loaded.Problems),
                    "RetailSync Demo POS — thiếu chứng chỉ hoặc token",
                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            Application.Run(new MainForm(loaded));
        }
        catch (ConfigurationException error)
        {
            MessageBox.Show(error.Message, "RetailSync Demo POS — cấu hình chưa đúng",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        catch (Exception error)
        {
            MessageBox.Show(error.ToString(), "RetailSync Demo POS — lỗi khởi động",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
