using System;
using System.Collections.Generic;
using System.Linq;
using Avalonia.Controls;
using Avalonia.LogicalTree;
using Avalonia.Media;
using Avalonia.VisualTree;

namespace UniversalDownloader.Avalonia;

public record ThemePalette(
    string Id,
    string Name,
    string WindowBackground,
    string CardBackground,
    string BorderBrush,
    string AccentColor,
    string SecondaryAccent
);

/// <summary>
/// Dynamic theme and accent palette manager for Avalonia desktop app.
/// Supports AMOLED True Black, Nord Frost, Cyberpunk Neon, Catppuccin Mocha, and Emerald Matrix.
/// </summary>
public static class ThemeManager
{
    public static readonly IReadOnlyList<ThemePalette> Palettes =
    [
        new("default", "Default Dark", "#0E0E12", "#1E1E24", "#27272A", "#38BDF8", "#6366F1"),
        new("amoled", "AMOLED Black", "#000000", "#09090B", "#18181B", "#38BDF8", "#3B82F6"),
        new("nord", "Nord Frost", "#2E3440", "#3B4252", "#434C5E", "#88C0D0", "#81A1C1"),
        new("cyberpunk", "Cyberpunk Neon", "#0D0221", "#1B063A", "#2E0854", "#00F0FF", "#F43F5E"),
        new("catppuccin", "Catppuccin Mocha", "#1E1E2E", "#181825", "#313244", "#CBA6F7", "#89B4FA"),
        new("emerald", "Emerald Matrix", "#02140D", "#062E1E", "#0B4A31", "#10B981", "#34D399"),
    ];

    public static ThemePalette GetPalette(string? id)
    {
        if (string.IsNullOrWhiteSpace(id)) return Palettes[0];
        return Palettes.FirstOrDefault(p => string.Equals(p.Id, id, StringComparison.OrdinalIgnoreCase)) ?? Palettes[0];
    }

    public static void ApplyTheme(Window window, string themeId)
    {
        var palette = GetPalette(themeId);
        try
        {
            window.Background = Brush.Parse(palette.WindowBackground);

            // Dynamically traverse logical children to theme cards and borders
            ApplyPaletteToVisualTree(window, palette);
        }
        catch
        {
            // Fallback gracefully on parsing errors
        }
    }

    private static void ApplyPaletteToVisualTree(Control root, ThemePalette palette)
    {
        var cardBrush = Brush.Parse(palette.CardBackground);
        var borderBrush = Brush.Parse(palette.BorderBrush);

        foreach (var control in root.GetLogicalDescendants())
        {
            if (control is Border border)
            {
                // If it's a content card with typical dark background
                if (border.Background is ISolidColorBrush scb)
                {
                    string hex = scb.Color.ToString();
                    // Match default card backgrounds
                    if (hex.Equals("#FF1E1E24", StringComparison.OrdinalIgnoreCase) ||
                        hex.Equals("#FF09090B", StringComparison.OrdinalIgnoreCase) ||
                        hex.Equals("#FF3B4252", StringComparison.OrdinalIgnoreCase) ||
                        hex.Equals("#FF1B063A", StringComparison.OrdinalIgnoreCase) ||
                        hex.Equals("#FF181825", StringComparison.OrdinalIgnoreCase) ||
                        hex.Equals("#FF062E1E", StringComparison.OrdinalIgnoreCase))
                    {
                        border.Background = cardBrush;
                        border.BorderBrush = borderBrush;
                    }
                }
            }
        }
    }
}
