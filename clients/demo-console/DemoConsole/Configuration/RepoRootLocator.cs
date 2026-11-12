namespace DemoConsole.Configuration;

/// <summary>Copied from the demo POS. Finds the repository root by walking up to the folder that holds compose.yaml.</summary>
public static class RepoRootLocator
{
    public static string Find(string? startDirectory = null)
    {
        var candidates = new List<string>();
        if (!string.IsNullOrWhiteSpace(startDirectory))
        {
            candidates.Add(startDirectory);
            var full = Path.GetFullPath(startDirectory);
            var dir = Directory.Exists(full) ? new DirectoryInfo(full) : new DirectoryInfo(Path.GetDirectoryName(full) ?? full);
            if (dir.Exists)
            {
                candidates.Add(dir.FullName);
            }
        }

        candidates.Add(AppContext.BaseDirectory);
        candidates.Add(Directory.GetCurrentDirectory());

        foreach (var candidate in candidates.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            var directory = new DirectoryInfo(Path.GetFullPath(candidate));
            while (directory is not null)
            {
                if (File.Exists(Path.Combine(directory.FullName, "compose.yaml")))
                {
                    return directory.FullName;
                }

                directory = directory.Parent;
            }
        }

        throw new ConfigurationException(
            $"Could not find the repository root (a folder containing compose.yaml) above '{startDirectory ?? AppContext.BaseDirectory}'.");
    }
}
