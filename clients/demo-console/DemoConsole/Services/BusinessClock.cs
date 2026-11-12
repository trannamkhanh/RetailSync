namespace DemoConsole.Services;

/// <summary>The business date of the middleware: UTC+7, as app/core/clock.today_local().</summary>
public static class BusinessClock
{
    public static readonly TimeSpan Offset = TimeSpan.FromHours(7);

    public static DateOnly Today(DateTime utcNow) => DateOnly.FromDateTime(utcNow.Add(Offset));

    public static DateTime ToLocal(DateTime utc) => utc.Add(Offset);

    public static int DaysLeft(DateOnly expiry, DateOnly today) => expiry.DayNumber - today.DayNumber;

    /// <summary>EXPIRED before today (not sellable under FEFO), else "OK, n d left".</summary>
    public static string BatchState(DateOnly expiry, DateOnly today)
    {
        var days = DaysLeft(expiry, today);
        return days < 0 ? "EXPIRED" : $"OK, {days} d left";
    }
}
