import { create, mplCore } from '@metaplex-foundation/mpl-core';
import { generateSigner } from '@metaplex-foundation/umi';
import { createUmi } from '@metaplex-foundation/umi-bundle-defaults';
import { base58 } from '@metaplex-foundation/umi/serializers';
import { walletAdapterIdentity } from '@metaplex-foundation/umi-signer-wallet-adapters';
import { useWallet } from '@solana/wallet-adapter-react';
import { useWalletModal } from '@solana/wallet-adapter-react-ui';
import { useCallback, useState } from 'react';

interface MintMomentButtonProps {
  matchId: number;
  eventId: string;
  eventType: string;
  minute: number;
  description: string;
}

interface MomentResponse {
  id: string;
  description: string;
  card_image_url: string | null;
  txline_seq: number | null;
  mint_address: string | null;
}

type MintStatus = 'idle' | 'creating' | 'minting' | 'saving' | 'minted';

// Public devnet RPC is heavily per-IP rate-limited and browser-hostile — a
// transient 429 during send/confirm surfaces as "Failed to fetch". For a
// reliable demo, set VITE_SOLANA_RPC_URL to a dedicated devnet endpoint.
const DEVNET_RPC_URL = import.meta.env.VITE_SOLANA_RPC_URL || 'https://api.devnet.solana.com';

function readableMintError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const normalized = message.toLowerCase();
  if (normalized.includes('user rejected') || normalized.includes('declined')) {
    return 'Mint cancelled in Phantom.';
  }
  if (normalized.includes('insufficient') || normalized.includes('0x1')) {
    return 'Not enough devnet SOL. Fund this wallet from faucet.solana.com and retry.';
  }
  if (normalized.includes('failed to fetch') || normalized.includes('rpc')) {
    return 'The Solana devnet RPC did not respond. Please retry in a moment.';
  }
  if (normalized.includes('signedtransaction')) {
    return 'Phantom appears to be on the wrong network. Open Phantom → Settings → Developer Settings → enable Testnet Mode and select Solana Devnet, then retry.';
  }
  return message || 'The moment could not be minted.';
}

export function MintMomentButton({
  matchId,
  eventId,
  eventType,
  minute,
  description,
}: MintMomentButtonProps) {
  const wallet = useWallet();
  const { setVisible } = useWalletModal();
  const [status, setStatus] = useState<MintStatus>('idle');
  const [moment, setMoment] = useState<MomentResponse | null>(null);
  const [explorerUrl, setExplorerUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const apiUrl = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8123';

  const handleMint = useCallback(async () => {
    if (!wallet.connected || !wallet.publicKey) {
      setVisible(true);
      return;
    }

    setError(null);
    try {
      let activeMoment = moment;
      if (activeMoment === null) {
        setStatus('creating');
        const createResponse = await fetch(`${apiUrl}/api/moments`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            match_id: matchId,
            event_id: eventId,
            event_type: eventType,
            minute,
          }),
        });
        if (!createResponse.ok) {
          throw new Error(`Moment card creation failed (${createResponse.status}).`);
        }
        activeMoment = (await createResponse.json()) as MomentResponse;
        setMoment(activeMoment);
      }

      setStatus('minting');
      const umi = createUmi(DEVNET_RPC_URL)
        .use(mplCore())
        .use(walletAdapterIdentity(wallet));
      const asset = generateSigner(umi);
      const metadataUrl = `${apiUrl}/api/moments/${activeMoment.id}/metadata`;
      const result = await create(umi, {
        asset,
        name: `MatchPulse: ${activeMoment.description}`.slice(0, 32),
        uri: metadataUrl,
      }).sendAndConfirm(umi);
      const mintAddress = String(asset.publicKey);
      const [mintTxSig] = base58.deserialize(result.signature);
      const nextExplorerUrl = `https://explorer.solana.com/address/${mintAddress}?cluster=devnet`;
      setExplorerUrl(nextExplorerUrl);

      setStatus('saving');
      const patchResponse = await fetch(`${apiUrl}/api/moments/${activeMoment.id}/mint`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wallet_address: wallet.publicKey.toBase58(),
          mint_address: mintAddress,
          mint_tx_sig: mintTxSig,
        }),
      });
      if (!patchResponse.ok) {
        setError('Mint succeeded, but saving the receipt failed. The explorer link is valid.');
      }
      setStatus('minted');
    } catch (mintError) {
      setStatus('idle');
      setError(readableMintError(mintError));
    }
  }, [apiUrl, description, eventId, eventType, matchId, minute, moment, setVisible, wallet]);

  const cardUrl =
    moment?.card_image_url && /^https?:\/\//.test(moment.card_image_url)
      ? moment.card_image_url
      : moment?.card_image_url
        ? `${apiUrl}/${moment.card_image_url.replace(/^\//, '')}`
        : null;
  const busy = status !== 'idle' && status !== 'minted';
  const buttonLabel = !wallet.connected
    ? 'Connect Phantom to mint'
    : status === 'creating'
      ? 'Creating card…'
      : status === 'minting'
        ? 'Approve in Phantom…'
        : status === 'saving'
          ? 'Saving proof…'
          : 'Mint verified moment';

  return (
    <div className="mt-3 border-t-2 border-black pt-3">
      {cardUrl ? (
        <img className="mb-3 w-full border-2 border-black" src={cardUrl} alt={moment?.description} />
      ) : moment ? (
        <p className="mb-3 inline-block border-2 border-black bg-brutal-yellow px-2 py-1 text-xs font-black uppercase">
          Verifiable data · TxLINE seq {moment.txline_seq ?? 'unavailable'}
        </p>
      ) : null}

      {explorerUrl ? (
        <a
          className="inline-block border-4 border-black bg-brutal-lime px-4 py-2 font-black uppercase shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]"
          href={explorerUrl}
          target="_blank"
          rel="noreferrer"
        >
          View minted asset ↗
        </a>
      ) : (
        <button
          type="button"
          onClick={handleMint}
          disabled={busy}
          className="border-4 border-black bg-brutal-blue px-4 py-2 font-black uppercase text-white shadow-[4px_4px_0px_0px_rgba(0,0,0,1)] disabled:cursor-wait disabled:opacity-60"
        >
          {buttonLabel}
        </button>
      )}
      {error ? <p className="mt-2 font-bold text-red-700">{error}</p> : null}
    </div>
  );
}
