import type { LiveMatchState } from '@/types/api';

interface ScoreHeaderProps {
  state: LiveMatchState | null;
  connected: boolean;
}

export function ScoreHeader({ state, connected }: ScoreHeaderProps) {
  return (
    <section className="border-4 border-black bg-white p-5 shadow-[6px_6px_0px_0px_rgba(0,0,0,1)]">
      <div className="mb-4 flex items-center justify-between gap-3">
        <span className="border-2 border-black bg-black px-3 py-1 text-xs font-black uppercase text-white">
          {state?.status ?? 'Waiting'} · {state?.minute ?? 0}&apos;
        </span>
        <span className="flex items-center gap-2 text-xs font-black uppercase">
          <span className={`h-3 w-3 border-2 border-black ${connected ? 'bg-green-400' : 'bg-red-400'}`} />
          {connected ? 'Connected' : 'Offline'}
        </span>
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4 text-center">
        <h2 className="text-xl font-black uppercase md:text-3xl">{state?.home_team ?? 'Home'}</h2>
        <div className="border-4 border-black bg-brutal-pink px-5 py-3 text-4xl font-black md:text-6xl">
          {state?.home_score ?? 0}–{state?.away_score ?? 0}
        </div>
        <h2 className="text-xl font-black uppercase md:text-3xl">{state?.away_team ?? 'Away'}</h2>
      </div>
    </section>
  );
}
