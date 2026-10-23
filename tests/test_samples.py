"""Synthetic chart fixtures only; never use live health records here."""
import json
from unittest.mock import Mock

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from garmin_mcp.history import History
from garmin_mcp.server import create_server


@pytest.fixture
def backend():
    client = Mock()
    # Deliberately shuffled descriptors and non-contiguous indices.
    client.get_activity_details.return_value = {
        'metricDescriptors': [
            {'key': key, 'metricsIndex': index, 'unit': {'key': unit}}
            for key, index, unit in [
                ('directPower', 5, 'watt'), ('directElevation', 6, 'foot'),
                ('directTimestamp', 2, 'ms'), ('directHeartRate', 1, 'bpm'),
                ('directSpeed', 3, 'kph'), ('directDoubleCadence', 4, 'stepsPerMinute'),
                ('directLatitude', 0, 'degree'),
            ]
        ],
        'activityDetailMetrics': [
            {'metrics': [42.123456, 120 + i, 1704067200000 + i * 1000, 9, 85, 200, 100]}
            for i in range(11)
        ],
        'geoPolylineDTO': {'polyline': 'PRIVATE-ROUTE'},
        'userProfileId': 'PRIVATE-ACCOUNT',
    }
    return client


def test_samples_units_indexing_and_privacy(backend, caplog):
    result = History('unused', backend).get_activity_samples(1)
    backend.get_activity_details.assert_called_once_with('1', maxchart=10000, maxpoly=0)
    assert result['source_sample_count'] == result['returned_sample_count'] == 11
    assert result['downsampled'] is False
    assert result['samples'][0] == {
        'timestamp': '2024-01-01T00:00:00Z', 'heart_rate': 120,
        'pace': 400, 'cadence': 85, 'power': 200, 'elevation': 30.48,
    }
    assert result['units']['cadence'] == 'stepsPerMinute'
    encoded = json.dumps(result) + caplog.text
    for secret in ('PRIVATE-ROUTE', 'PRIVATE-ACCOUNT', '42.123456', 'directLatitude', 'geoPolylineDTO'):
        assert secret not in encoded


def test_downsampling_selects_actual_points_and_endpoints(backend):
    history = History('unused', backend)
    result = history.get_activity_samples(1, max_points=3, interval_seconds=2)
    assert [s['heart_rate'] for s in result['samples']] == [120, 124, 130]
    assert result['source_sample_count'] == 11
    assert result['returned_sample_count'] == 3
    assert result['downsampled'] is True
    result = history.get_activity_samples(1, interval_seconds=4)
    assert [s['heart_rate'] for s in result['samples']] == [120, 124, 128]


def test_missing_invalid_and_zero_measurements(backend):
    metrics = backend.get_activity_details.return_value['activityDetailMetrics'][0]['metrics']
    metrics[1:] = [0, 1704067200000, 0, 0, 0, -10]
    result = History('unused', backend).get_activity_samples(1)['samples'][0]
    assert result['heart_rate'] is None
    assert result['pace'] is None
    assert result['power'] == result['cadence'] == 0
    assert result['elevation'] == -3.048
    metrics[1:] = [True, 1704067200000, float('nan'), None, float('inf'), 'PRIVATE']
    result = History('unused', backend).get_activity_samples(1)['samples'][0]
    assert all(result[k] is None for k in ('heart_rate', 'pace', 'cadence', 'power', 'elevation'))
    json.dumps(result, allow_nan=False)


def test_unknown_units_short_rows_and_missing_timestamps(backend):
    data = backend.get_activity_details.return_value
    for descriptor in data['metricDescriptors']:
        if descriptor['key'] != 'directTimestamp':
            descriptor['unit']['key'] = 'PRIVATE-UNIT'
    data['activityDetailMetrics'] = [{'metrics': [0, 100, 1704067200000]}, {'metrics': []}]
    result = History('unused', backend).get_activity_samples(1)
    assert len(result['samples']) == 1
    assert result['units']['cadence'] is None
    assert 'PRIVATE-UNIT' not in json.dumps(result)
    assert all(v is None for k, v in result['samples'][0].items() if k != 'timestamp')


@pytest.mark.parametrize('kwargs', [
    {'activity_id': 0}, {'activity_id': True}, {'activity_id': '../secret'},
    {'max_points': 1}, {'max_points': 10001}, {'max_points': 2.5},
    {'interval_seconds': 0}, {'interval_seconds': 86401}, {'interval_seconds': True},
])
def test_validation_before_network(backend, kwargs):
    with pytest.raises(ToolError):
        History('unused', backend).get_activity_samples(**({'activity_id': 1} | kwargs))
    backend.get_activity_details.assert_not_called()


@pytest.mark.parametrize('data', [None, {'activityDetailMetrics': None},
    {'metricDescriptors': [{'key': 'PRIVATE', 'unit': None}] , 'activityDetailMetrics': [{'metrics': None}]}])
def test_malformed_data_is_sanitized(backend, data):
    backend.get_activity_details.return_value = data
    with pytest.raises(ToolError, match='decoded safely') as error:
        History('unused', backend).get_activity_samples(1)
    assert 'PRIVATE' not in str(error.value)


def test_empty_and_upstream_failure(backend):
    backend.get_activity_details.return_value = {}
    result = History('unused', backend).get_activity_samples(1)
    assert result['samples'] == []
    assert result['returned_sample_count'] == 0
    backend.get_activity_details.side_effect = RuntimeError('PRIVATE-TOKEN PRIVATE-GPS')
    with pytest.raises(ToolError) as error:
        History('unused', backend).get_activity_samples(1)
    assert 'PRIVATE' not in str(error.value)


@pytest.mark.asyncio
async def test_samples_mcp_schema_and_call(backend):
    async with Client(create_server(History('unused', backend))) as client:
        tool = next(t for t in await client.list_tools() if t.name == 'get_activity_samples')
        assert tool.annotations.readOnlyHint
        assert tool.annotations.destructiveHint is False
        assert tool.inputSchema['required'] == ['activity_id']
        result = await client.call_tool('get_activity_samples', {'activity_id': 1, 'max_points': 2})
        assert len(result.data['samples']) == 2
        assert result.data['samples'][-1]['heart_rate'] == 130
        with pytest.raises(Exception):
            await client.call_tool('get_activity_samples', {'activity_id': 0})
