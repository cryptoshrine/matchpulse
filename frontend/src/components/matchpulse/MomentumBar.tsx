interface MomentumBarProps {
  momentumDelta: number;
}

export function MomentumBar({ momentumDelta }: MomentumBarProps) {
  const boundedDelta = Math.max(-1, Math.min(1, momentumDelta));
  const homeWidth = Math.max(0, boundedDelta) * 50;
  const awayWidth = Math.max(0, -boundedDelta) * 50;

  return (
    <section className="border-4 border-black bg-white p-4 shadow-[5px_5px_0px_0px_rgba(0,0,0,1)]">
      <div className="mb-2 flex justify-between text-sm font-black uppercase">
        <span>Home pressure</span>
        <span>Momentum</span>
        <span>Away pressure</span>
      </div>
      <div className="relative h-12 overflow-hidden border-4 border-black bg-gray-200">
        <div className="absolute inset-y-0 right-1/2 bg-brutal-blue" style={{ width: `${homeWidth}%` }} />
        <div className="absolute inset-y-0 left-1/2 bg-brutal-pink" style={{ width: `${awayWidth}%` }} />
        <div className="absolute inset-y-0 left-1/2 w-1 -translate-x-1/2 bg-black" />
      </div>
      <p className="mt-2 text-center font-mono text-sm font-bold">{boundedDelta.toFixed(2)}</p>
    </section>
  );
}
