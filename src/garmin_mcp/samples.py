"""Allowlisted chart decoding; never return raw Garmin payloads."""
from datetime import datetime, timezone
from math import isfinite

from fastmcp.exceptions import ToolError

CHART_LIMIT = 10000


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if isfinite(value) else None


def decode_samples(data: dict, max_points: int, interval_seconds: int | None) -> dict:
    try:
        descriptors = {d['key']: d for d in data.get('metricDescriptors', [])}
        frames = data.get('activityDetailMetrics', [])
        if not isinstance(frames, list):
            raise ValueError

        def read(metrics, key, units):
            descriptor = descriptors.get(key, {})
            index = descriptor.get('metricsIndex')
            unit = descriptor.get('unit', {}).get('key')
            if type(index) is not int or index < 0 or index >= len(metrics) or unit not in units:
                return None
            value = number(metrics[index])
            return number(value * units[unit]) if value is not None else None

        cadence_key = next((key for key in ('directDoubleCadence', 'directRunCadence', 'directBikeCadence') if key in descriptors), None)
        cadence_unit = descriptors.get(cadence_key, {}).get('unit', {}).get('key')
        # Keep Garmin cadence values and units, without guessing step/stride conversion.
        if cadence_unit not in ('stepsPerMinute', 'rpm', 'spm'):
            cadence_unit = None
        samples = []
        for frame in frames:
            metrics = frame['metrics']
            if not isinstance(metrics, list):
                raise ValueError
            timestamp = read(metrics, 'directTimestamp', {'ms': 0.001, 'second': 1})
            if timestamp is None:
                continue
            timestamp_text = datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace('+00:00', 'Z')
            speed = read(metrics, 'directSpeed', {'mps': 1, 'kph': 1 / 3.6, 'mph': 0.44704, 'hmph': 1 / 36, 'hydph': 0.0254})
            hr = read(metrics, 'directHeartRate', {'bpm': 1})
            power = read(metrics, 'directPower', {'watt': 1})
            cadence = read(metrics, cadence_key, {cadence_unit: 1}) if cadence_unit else None
            samples.append((timestamp, {
                'timestamp': timestamp_text,
                'heart_rate': hr if hr is not None and hr > 0 else None,
                'pace': 1000 / speed if speed is not None and speed > 0 and isfinite(1000 / speed) else None,
                'cadence': cadence if cadence is not None and cadence >= 0 else None,
                'power': power if power is not None and power >= 0 else None,
                'elevation': read(metrics, 'directElevation', {'meter': 1, 'foot': 0.3048, 'yard': 0.9144, 'kilometer': 1000, 'mile': 1609.344}),
            }))
        samples.sort(key=lambda item: item[0])
        source_count = len(samples)
        if interval_seconds is not None:
            selected = []
            for timestamp, sample in samples:
                if not selected or timestamp - selected[-1][0] >= interval_seconds:
                    selected.append((timestamp, sample))
            samples = selected
        if len(samples) > max_points:
            # Evenly spaced actual observations, preserving both endpoints.
            samples = [samples[i * (len(samples) - 1) // (max_points - 1)] for i in range(max_points)]
        return {
            'samples': [sample for _, sample in samples],
            'units': {'timestamp': 'UTC ISO-8601', 'heart_rate': 'bpm', 'pace': 'seconds/kilometer',
                      'cadence': cadence_unit, 'power': 'watts', 'elevation': 'meters'},
            'source_sample_count': source_count,
            'returned_sample_count': len(samples),
            'downsampled': len(samples) < source_count,
            'max_points': max_points, 'interval_seconds': interval_seconds,
            'upstream_chart_limit': CHART_LIMIT,
            'note': 'Garmin may simplify chart data before returning it; these are not guaranteed raw device samples. Downsampling selects observations, never averages or interpolates. Cadence retains Garmin values and unit labels; do not infer steps versus strides. Null means unavailable or unsupported units. Absolute timestamps and health measurements remain sensitive. Coordinates, routes and account details are omitted.',
        }
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, OSError):
        raise ToolError('Garmin sample data could not be decoded safely.') from None
