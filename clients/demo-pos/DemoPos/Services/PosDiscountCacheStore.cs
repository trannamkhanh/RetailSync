using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Json;
using DemoPos.Models;

namespace DemoPos.Services;

public sealed record PosDiscountCacheEntry(PosDiscountList List, DateTime UpdatedAtLocal);

/// <summary>
/// Persists the last valid LIVE discount list for each terminal in the same local data
/// directory as <see cref="DurableEventQueue"/>, so an offline restart on the same
/// UTC+7 business date keeps the last fetched discount prices (DSH50-10).
/// </summary>
public sealed class PosDiscountCacheStore
{
    private const string TimestampFormat = "yyyy-MM-dd'T'HH:mm:ss";
    private readonly string _directory;

    public PosDiscountCacheStore(string directory)
    {
        if (string.IsNullOrWhiteSpace(directory))
        {
            throw new ArgumentException("Cache directory must be specified.", nameof(directory));
        }

        _directory = directory;
    }

    public string PathFor(string posId)
    {
        if (string.IsNullOrWhiteSpace(posId)
            || posId.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0
            || posId is "." or "..")
        {
            throw new ArgumentException("Invalid terminal ID", nameof(posId));
        }

        return Path.Combine(_directory, posId + ".discounts.json");
    }

    public PosDiscountCacheEntry? Load(string posId, string expectedStoreId, string expectedPosBaseUrl)
    {
        string path;
        try
        {
            path = PathFor(posId);
        }
        catch (ArgumentException error)
        {
            Trace.TraceWarning($"[PB-50] Ignoring discount cache for invalid pos_id '{posId}': {error.Message}");
            return null;
        }

        if (!File.Exists(path))
        {
            return null;
        }

        string raw;
        try
        {
            raw = File.ReadAllText(path, Encoding.UTF8);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            Trace.TraceWarning($"[PB-50] Could not read discount cache '{path}': {error.Message}");
            return null;
        }

        return TryParseCache(raw, expectedStoreId, expectedPosBaseUrl, path);
    }

    public void Save(string posId, string storeId, string posBaseUrl, PosDiscountList list, DateTime updatedAtLocal)
    {
        ArgumentNullException.ThrowIfNull(list);
        var targetPath = PathFor(posId);
        var temporary = $"{targetPath}.{Guid.NewGuid():N}.tmp";
        try
        {
            Directory.CreateDirectory(_directory);
            var bytes = SerializeCache(storeId, posBaseUrl, list, updatedAtLocal);
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                stream.Write(bytes);
                stream.Flush(true);
            }

            MoveWithRetry(temporary, targetPath);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            Trace.TraceWarning($"[PB-50] Could not persist discount cache '{targetPath}': {error.Message}");
            TryDeleteQuietly(temporary);
        }
    }

    public void Clear(string posId)
    {
        string path;
        try
        {
            path = PathFor(posId);
        }
        catch (ArgumentException)
        {
            return;
        }

        TryDeleteQuietly(path);
    }

    private static byte[] SerializeCache(string storeId, string posBaseUrl, PosDiscountList list, DateTime updatedAtLocal)
    {
        using var buffer = new MemoryStream();
        using (var writer = new Utf8JsonWriter(buffer))
        {
            writer.WriteStartObject();
            writer.WriteString("store_id", storeId.Trim());
            writer.WriteString("pos_base_url", NormalizeBaseUrl(posBaseUrl));
            writer.WriteString("business_date", list.BusinessDate.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture));
            writer.WriteString("updated_at_local", updatedAtLocal.ToString(TimestampFormat, CultureInfo.InvariantCulture));
            writer.WriteStartArray("items");
            foreach (var item in list.Items)
            {
                writer.WriteStartObject();
                writer.WriteString("sku", item.Sku);
                writer.WriteNumber("discount_pct", item.DiscountPct);
                writer.WriteNumber("discounted_price", item.DiscountedPrice);
                writer.WriteEndObject();
            }

            writer.WriteEndArray();
            writer.WriteEndObject();
        }

        return buffer.ToArray();
    }

    private static PosDiscountCacheEntry? TryParseCache(string raw, string expectedStoreId, string expectedPosBaseUrl, string path)
    {
        if (!PosDiscounts.TryParse(raw, out var list, out var parseError) || list is null)
        {
            Trace.TraceWarning($"[PB-50] Ignoring invalid discount cache '{path}': {parseError}");
            return null;
        }

        try
        {
            using var document = JsonDocument.Parse(raw);
            var root = document.RootElement;

            if (!root.TryGetProperty("store_id", out var storeProp)
                || storeProp.ValueKind != JsonValueKind.String
                || string.IsNullOrWhiteSpace(storeProp.GetString()))
            {
                Trace.TraceWarning($"[PB-50] Ignoring discount cache '{path}': missing 'store_id'.");
                return null;
            }

            if (!root.TryGetProperty("pos_base_url", out var urlProp)
                || urlProp.ValueKind != JsonValueKind.String
                || string.IsNullOrWhiteSpace(urlProp.GetString()))
            {
                Trace.TraceWarning($"[PB-50] Ignoring discount cache '{path}': missing 'pos_base_url'.");
                return null;
            }

            if (!string.Equals(storeProp.GetString()!.Trim(), expectedStoreId.Trim(), StringComparison.OrdinalIgnoreCase)
                || !string.Equals(NormalizeBaseUrl(urlProp.GetString()!), NormalizeBaseUrl(expectedPosBaseUrl), StringComparison.OrdinalIgnoreCase))
            {
                return null;
            }

            if (!root.TryGetProperty("updated_at_local", out var updatedProp)
                || updatedProp.ValueKind != JsonValueKind.String
                || !DateTime.TryParseExact(updatedProp.GetString(), TimestampFormat,
                    CultureInfo.InvariantCulture, DateTimeStyles.None, out var updatedAtLocal))
            {
                Trace.TraceWarning($"[PB-50] Ignoring discount cache '{path}': missing or invalid 'updated_at_local'.");
                return null;
            }

            return new PosDiscountCacheEntry(list, DateTime.SpecifyKind(updatedAtLocal, DateTimeKind.Local));
        }
        catch (JsonException error)
        {
            Trace.TraceWarning($"[PB-50] Ignoring corrupt discount cache '{path}': {error.Message}");
            return null;
        }
    }

    private static string NormalizeBaseUrl(string url) => url.Trim().TrimEnd('/');

    private static void MoveWithRetry(string source, string destination)
    {
        for (var attempt = 0; ; attempt++)
        {
            try
            {
                File.Move(source, destination, overwrite: true);
                return;
            }
            catch (IOException error) when (attempt < 5 && (error.HResult & 0xffff) is 32 or 33)
            {
                Thread.Sleep(10);
            }
        }
    }

    private static void TryDeleteQuietly(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            Trace.TraceWarning($"[PB-50] Could not remove discount cache file '{path}': {error.Message}");
        }
    }
}
