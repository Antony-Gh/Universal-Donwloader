using System;
using System.Collections.Generic;
using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using UniversalDownloader.Core;

namespace UniversalDownloader.Avalonia;

/// <summary>
/// Real-time live download speed and bandwidth history visualizer graph.
/// Renders smooth vector polyline with gradient area fill and peak tracking.
/// </summary>
public class BandwidthGraphControl : Control
{
    private const int MaxSamples = 50;
    private readonly List<double> _samples = new();
    private double _peakSpeed = 1024.0 * 1024.0; // default 1 MB/s scale minimum
    private double _currentSpeed = 0;

    public double CurrentSpeed => _currentSpeed;
    public double PeakSpeed => _peakSpeed;

    public BandwidthGraphControl()
    {
        ClipToBounds = true;
    }

    public void AddSample(double speedBytesPerSec)
    {
        _currentSpeed = Math.Max(0, speedBytesPerSec);
        _samples.Add(_currentSpeed);
        if (_samples.Count > MaxSamples)
        {
            _samples.RemoveAt(0);
        }

        double max = 1024.0 * 1024.0;
        foreach (var s in _samples)
        {
            if (s > max) max = s;
        }
        _peakSpeed = max;

        InvalidateVisual();
    }

    public void Reset()
    {
        _samples.Clear();
        _currentSpeed = 0;
        _peakSpeed = 1024.0 * 1024.0;
        InvalidateVisual();
    }

    public override void Render(DrawingContext context)
    {
        base.Render(context);

        var bounds = Bounds;
        if (bounds.Width <= 10 || bounds.Height <= 10) return;

        double width = bounds.Width;
        double height = bounds.Height;

        // Background
        var bgBrush = new SolidColorBrush(Color.Parse("#101016"));
        var borderPen = new Pen(new SolidColorBrush(Color.Parse("#272738")), 1.0);
        context.DrawRectangle(bgBrush, borderPen, new Rect(0, 0, width, height), 6, 6);

        // Guideline: 50% line
        var guidePen = new Pen(new SolidColorBrush(Color.FromArgb(40, 255, 255, 255)), 1.0, dashStyle: DashStyle.Dash);
        double midY = height / 2.0;
        context.DrawLine(guidePen, new Point(0, midY), new Point(width, midY));

        if (_samples.Count < 2)
        {
            // Empty / waiting state
            var emptyText = new FormattedText(
                "Awaiting bandwidth data...",
                CultureInfo.InvariantCulture,
                FlowDirection.LeftToRight,
                new Typeface("Inter, Segoe UI, sans-serif"),
                11,
                new SolidColorBrush(Color.Parse("#64748B"))
            );
            context.DrawText(emptyText, new Point((width - emptyText.Width) / 2.0, (height - emptyText.Height) / 2.0));
            return;
        }

        // Build polygon points for area fill and stroke
        double stepX = width / (MaxSamples - 1);
        int startIndex = MaxSamples - _samples.Count;
        double topPadding = 6.0;
        double bottomPadding = 6.0;
        double usableHeight = height - topPadding - bottomPadding;

        var points = new List<Point>(_samples.Count);
        for (int i = 0; i < _samples.Count; i++)
        {
            double x = (startIndex + i) * stepX;
            double ratio = Math.Clamp(_samples[i] / _peakSpeed, 0.0, 1.0);
            double y = height - bottomPadding - (ratio * usableHeight);
            points.Add(new Point(x, y));
        }

        // Draw gradient area fill under line
        var fillGeometry = new StreamGeometry();
        using (var sgc = fillGeometry.Open())
        {
            sgc.BeginFigure(new Point(points[0].X, height), true);
            foreach (var pt in points)
            {
                sgc.LineTo(pt);
            }
            sgc.LineTo(new Point(points[^1].X, height));
            sgc.EndFigure(true);
        }

        var areaBrush = new LinearGradientBrush
        {
            StartPoint = new RelativePoint(0, 0, RelativeUnit.Relative),
            EndPoint = new RelativePoint(0, 1, RelativeUnit.Relative),
            GradientStops =
            [
                new GradientStop(Color.FromArgb(90, 56, 189, 248), 0.0),
                new GradientStop(Color.FromArgb(10, 37, 99, 235), 1.0)
            ]
        };
        context.DrawGeometry(areaBrush, null, fillGeometry);

        // Draw line stroke
        var lineGeometry = new StreamGeometry();
        using (var lgc = lineGeometry.Open())
        {
            lgc.BeginFigure(points[0], false);
            for (int i = 1; i < points.Count; i++)
            {
                lgc.LineTo(points[i]);
            }
            lgc.EndFigure(false);
        }

        var strokePen = new Pen(new SolidColorBrush(Color.Parse("#38BDF8")), 1.8);
        context.DrawGeometry(null, strokePen, lineGeometry);

        // Draw stats badge in top-right
        string peakFormatted = PlatformUtils.FormatBytes((long)_peakSpeed);
        string curFormatted = PlatformUtils.FormatBytes((long)_currentSpeed);
        var statsText = new FormattedText(
            $"Cur: {curFormatted}/s  •  Peak: {peakFormatted}/s",
            CultureInfo.InvariantCulture,
            FlowDirection.LeftToRight,
            new Typeface("Inter, Segoe UI, sans-serif"),
            10.5,
            new SolidColorBrush(Color.Parse("#94A3B8"))
        );
        context.DrawText(statsText, new Point(width - statsText.Width - 10, 4));
    }
}
