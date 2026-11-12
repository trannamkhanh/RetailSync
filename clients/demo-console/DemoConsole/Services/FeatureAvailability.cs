using DemoConsole.Models;

namespace DemoConsole.Services;

public enum FeatureState
{
    /// <summary>Not checked yet, or the middleware did not answer: the button stays enabled.</summary>
    Unknown,
    Deployed,
    NotDeployed,
}

/// <summary>
/// The 404-means-not-deployed rule. A feature whose route is not on main yet gets a
/// disabled button with the reason; after the pull request merges and the middleware
/// restarts, the same build finds the route and enables it.
///
/// Routes are probed with a GET that has no side effect: FastAPI answers 405 for a
/// POST-only route that exists and 404 for one that does not. A job route exists for
/// every name, so a job is marked not deployed only when pressing its button answers
/// 404 with code NOT_FOUND.
/// </summary>
public static class FeatureAvailability
{
    public static FeatureState FromProbe(ApiResult probe)
    {
        if (probe.IsUnreachable)
        {
            return FeatureState.Unknown;
        }

        return probe.Status == 404 ? FeatureState.NotDeployed : FeatureState.Deployed;
    }

    /// <summary>The answer to pressing the button: only 404 means the feature is missing.</summary>
    public static FeatureState FromAction(ApiResult answer, FeatureState current)
    {
        if (answer.IsUnreachable)
        {
            return current;
        }

        return answer.Status == 404 ? FeatureState.NotDeployed : FeatureState.Deployed;
    }

    public static string Reason(string feature, FeatureState state) => state switch
    {
        FeatureState.NotDeployed => $"{feature}: not on this middleware yet (404). It works after its pull request merges and the middleware restarts.",
        FeatureState.Unknown => $"{feature}: not checked yet.",
        _ => string.Empty,
    };
}
