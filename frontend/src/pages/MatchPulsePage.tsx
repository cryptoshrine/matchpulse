import '@solana/wallet-adapter-react-ui/styles.css';

import { ConnectionProvider, WalletProvider } from '@solana/wallet-adapter-react';
import { WalletModalProvider, WalletMultiButton } from '@solana/wallet-adapter-react-ui';
import { PhantomWalletAdapter } from '@solana/wallet-adapter-phantom';
import { clusterApiUrl } from '@solana/web3.js';
import { useCallback, useMemo, useState } from 'react';

import { AlertBanner } from '@/components/matchpulse/AlertBanner';
import { MomentumBar } from '@/components/matchpulse/MomentumBar';
import { NarrativeFeed } from '@/components/matchpulse/NarrativeFeed';
import { RecordingPicker } from '@/components/matchpulse/RecordingPicker';
import { ScoreHeader } from '@/components/matchpulse/ScoreHeader';
import { useMatchPulse } from '@/hooks/useMatchPulse';
import type { LiveMatchState, LiveNotification } from '@/types/api';

const MAX_NOTIFICATIONS = 100;
const DEVNET_ENDPOINT = clusterApiUrl('devnet');

function MatchPulseExperience() {
  const [matchId, setMatchId] = useState<number | null>(null);
  const [matchState, setMatchState] = useState<LiveMatchState | null>(null);
  const [notifications, setNotifications] = useState<LiveNotification[]>([]);
  const [momentumDelta, setMomentumDelta] = useState(0);
  const [latestAlert, setLatestAlert] = useState<LiveNotification | null>(null);

  const handleReplayStarted = useCallback((newMatchId: number) => {
    setMatchId(newMatchId);
    setMatchState(null);
    setNotifications([]);
    setMomentumDelta(0);
    setLatestAlert(null);
  }, []);

  const handleNotification = useCallback((notification: LiveNotification) => {
    setNotifications((current) => [...current, notification].slice(-MAX_NOTIFICATIONS));
    if (notification.notification_type === 'momentum_shift') {
      setLatestAlert(notification);
      if (notification.momentum_delta !== undefined) {
        setMomentumDelta(notification.momentum_delta);
      }
    }
  }, []);

  const handleStateSnapshot = useCallback(
    (state: LiveMatchState | null, currentMomentumDelta: number) => {
      setMatchState(state);
      setMomentumDelta(currentMomentumDelta);
    },
    [],
  );

  const { connected } = useMatchPulse({
    matchId,
    onNotification: handleNotification,
    onStateSnapshot: handleStateSnapshot,
    enabled: matchId !== null,
  });

  return (
    <main className="min-h-screen bg-[#f5f1e8] px-4 py-8 text-black md:px-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <header className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <div>
            <p className="font-mono text-sm font-black uppercase tracking-[0.25em]">
              Ball-AI presents
            </p>
            <h1 className="text-5xl font-black uppercase leading-none md:text-7xl">MatchPulse</h1>
            <p className="mt-2 max-w-2xl text-lg font-bold">
              Real-time World Cup score, match story, and momentum intelligence.
            </p>
          </div>
          <div className="flex flex-col items-start gap-2 md:items-end">
            <WalletMultiButton className="!rounded-none !border-4 !border-black !bg-brutal-pink !font-black !uppercase !shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]" />
            <p className="max-w-sm text-xs font-bold">
              Need devnet SOL? Use faucet.solana.com or{' '}
              <code>solana airdrop 2 &lt;address&gt; --url devnet</code>.
            </p>
          </div>
        </header>

        <RecordingPicker onReplayStarted={handleReplayStarted} />
        <AlertBanner alert={latestAlert} />
        <ScoreHeader state={matchState} connected={connected} />
        <MomentumBar momentumDelta={momentumDelta} />
        <NarrativeFeed notifications={notifications} />

        <footer className="border-t-4 border-black py-3 text-center font-black uppercase">
          Live data powered by TxODDS TxLINE
        </footer>
      </div>
    </main>
  );
}

export default function MatchPulsePage() {
  const wallets = useMemo(() => [new PhantomWalletAdapter()], []);

  if (import.meta.env.VITE_MATCHPULSE_ENABLED !== 'true') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-white p-6">
        <p className="border-4 border-black bg-brutal-yellow p-6 text-xl font-black uppercase shadow-[6px_6px_0px_0px_rgba(0,0,0,1)]">
          MatchPulse is not enabled
        </p>
      </main>
    );
  }

  return (
    <ConnectionProvider endpoint={DEVNET_ENDPOINT}>
      <WalletProvider wallets={wallets} autoConnect>
        <WalletModalProvider>
          <MatchPulseExperience />
        </WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  );
}
