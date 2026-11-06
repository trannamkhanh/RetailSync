namespace DemoPos.Configuration;

/// <summary>Raised when the committed configuration or a demo asset is unusable.</summary>
public sealed class ConfigurationException : Exception
{
    public ConfigurationException(string message) : base(message)
    {
    }

    public ConfigurationException(string message, Exception inner) : base(message, inner)
    {
    }
}
