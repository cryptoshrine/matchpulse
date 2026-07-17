import { useEffect, useMemo, useState } from 'react';

interface Recording {
  filename: string;
  size_bytes: number;
  match_id: number | null;
  home_team: string | null;
  away_team: string | null;
  home_team_id: number | null;
  away_team_id: number | null;
}

interface RecordingsResponse {
  recordings: Recording[];
  count: number;
}

interface RecordingPickerProps {
  onReplayStarted: (matchId: number) => void;
}

const SPEEDS = [1, 5, 10, 30, 60] as const;
const HERO_RECORDING_FILENAME = '18237038_updates_recovery.jsonl';

/**
 * Live SSE captures use a `{fixture}_{YYYYMMDD}_{HHMMSS}.jsonl` name. They lack
 * in-band lineups (raw IDs, not names), so we hide them from the picker and keep
 * only the REST recovery/historical files, which carry the full roster.
 */
function isLiveRecording(filename: string): boolean {
  return /_\d{8}_\d{6}\.jsonl$/.test(filename);
}

/** Picker label: "Home vs Away", falling back to the filename. */
function recordingLabel(recording: Recording): string {
  return recording.home_team && recording.away_team
    ? `${recording.home_team} vs ${recording.away_team}`
    : recording.filename;
}

export function RecordingPicker({ onReplayStarted }: RecordingPickerProps) {
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [selectedFilename, setSelectedFilename] = useState('');
  const [speed, setSpeed] = useState<number>(30);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const apiUrl = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8123';

  useEffect(() => {
    const controller = new AbortController();
    const loadRecordings = async () => {
      try {
        const response = await fetch(`${apiUrl}/api/matchpulse/recordings`, {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Could not load recordings (${response.status})`);
        const payload = (await response.json()) as RecordingsResponse;
        const visible = payload.recordings.filter(
          (recording) => !isLiveRecording(recording.filename),
        );
        setRecordings(visible);
        const heroRecording = visible.find(
          (recording) => recording.filename === HERO_RECORDING_FILENAME,
        );
        const firstReplayable = visible.find((recording) => recording.match_id !== null);
        setSelectedFilename(heroRecording?.filename ?? firstReplayable?.filename ?? '');
      } catch (requestError) {
        if (!(requestError instanceof DOMException && requestError.name === 'AbortError')) {
          setError(requestError instanceof Error ? requestError.message : 'Could not load recordings');
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void loadRecordings();
    return () => controller.abort();
  }, [apiUrl]);

  const selectedRecording = useMemo(
    () => recordings.find((recording) => recording.filename === selectedFilename) ?? null,
    [recordings, selectedFilename],
  );

  const startReplay = async () => {
    if (selectedRecording?.match_id === null || selectedRecording === null) return;
    setStarting(true);
    setError(null);
    try {
      const response = await fetch(`${apiUrl}/api/matchpulse/replay`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          match_id: selectedRecording.match_id,
          recording_file: selectedRecording.filename,
          speed,
          home_team: selectedRecording.home_team,
          away_team: selectedRecording.away_team,
          home_team_id: selectedRecording.home_team_id,
          away_team_id: selectedRecording.away_team_id,
        }),
      });
      if (!response.ok) {
        const payload = (await response.json()) as { detail?: string };
        throw new Error(payload.detail ?? `Could not start replay (${response.status})`);
      }
      const payload = (await response.json()) as { match_id: number };
      onReplayStarted(payload.match_id);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not start replay');
    } finally {
      setStarting(false);
    }
  };

  return (
    <section className="border-4 border-black bg-brutal-yellow p-4 shadow-[6px_6px_0px_0px_rgba(0,0,0,1)]">
      <h2 className="mb-3 text-xl font-black uppercase">Replay control</h2>
      <div className="grid gap-3 md:grid-cols-[1fr_auto_auto]">
        <label className="flex flex-col gap-1 font-bold uppercase">
          Recording
          <select
            className="h-12 border-4 border-black bg-white px-3 font-bold"
            value={selectedFilename}
            onChange={(event) => setSelectedFilename(event.target.value)}
            disabled={loading}
          >
            <option value="">{loading ? 'Loading…' : 'Choose a recorded match'}</option>
            {recordings.map((recording) => (
              <option
                key={recording.filename}
                value={recording.filename}
                disabled={recording.match_id === null}
              >
                {recordingLabel(recording)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 font-bold uppercase">
          Speed
          <select
            className="h-12 border-4 border-black bg-white px-3 font-black"
            value={speed}
            onChange={(event) => setSpeed(Number(event.target.value))}
          >
            {SPEEDS.map((value) => (
              <option key={value} value={value}>
                {value}x
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="self-end border-4 border-black bg-brutal-blue px-5 py-2.5 font-black uppercase text-white shadow-[4px_4px_0px_0px_rgba(0,0,0,1)] disabled:cursor-not-allowed disabled:opacity-50"
          onClick={() => void startReplay()}
          disabled={selectedRecording?.match_id == null || starting}
        >
          {starting ? 'Starting…' : 'Start replay'}
        </button>
      </div>
      {error && <p className="mt-3 border-2 border-black bg-red-200 p-2 font-bold">{error}</p>}
    </section>
  );
}
