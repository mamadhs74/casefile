import { useChannels, useStrategies } from '../api/queries';
import type { ChannelRead, Platform, StrategyRead } from '../api/subjects';
import { EmptyState } from '../components/ui/EmptyState';
import { Skeleton } from '../components/ui/Skeleton';

const PLATFORMS: Platform[] = ['youtube', 'tiktok', 'instagram', 'facebook'];

const platformLabels: Record<Platform, string> = {
  youtube: 'YouTube',
  tiktok: 'TikTok',
  instagram: 'Instagram',
  facebook: 'Facebook',
};

function PlatformRow({
  platform,
  channel,
}: {
  platform: Platform;
  channel: ChannelRead | undefined;
}) {
  return (
    <div className="flex items-center justify-between rounded-md border border-ink/10 bg-paper px-4 py-3">
      <span className="font-sans text-sm font-medium text-ink">{platformLabels[platform]}</span>
      {channel ? (
        <div className="text-right">
          <p className="text-sm text-ink">{channel.display_name}</p>
          <p className="font-mono text-xs text-ink-muted">{channel.external_account_id}</p>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <div className="text-right">
            <p className="text-sm text-ink-muted">Not connected</p>
            <p className="text-xs text-ink-muted">No OAuth flow built yet</p>
          </div>
          <button
            type="button"
            disabled
            title="Connecting isn't built yet — there's no OAuth flow for this platform."
            className="cursor-not-allowed rounded-md border border-ink/15 px-3 py-1.5 font-sans text-sm text-ink-muted opacity-50"
          >
            Connect
          </button>
        </div>
      )}
    </div>
  );
}

function StrategyChannels({ strategy }: { strategy: StrategyRead }) {
  const { data: channels, isLoading, isError, error } = useChannels(strategy.slug);

  return (
    <section className="flex flex-col gap-3">
      <h2 className="font-sans text-sm font-semibold uppercase tracking-wide text-ink-muted">
        {strategy.name}
      </h2>

      {isLoading && (
        <div className="flex flex-col gap-2">
          {PLATFORMS.map((platform) => (
            <Skeleton key={platform} className="h-14 w-full" />
          ))}
        </div>
      )}

      {isError && (
        <EmptyState
          tone="error"
          title="Couldn't load channels"
          description={error instanceof Error ? error.message : 'Something went wrong.'}
        />
      )}

      {channels && (
        <div className="flex flex-col gap-2">
          {PLATFORMS.map((platform) => (
            <PlatformRow
              key={platform}
              platform={platform}
              channel={channels.find((c) => c.platform === platform && c.is_active)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export function PublishingPage() {
  const { data: strategies, isLoading, isError, error } = useStrategies();

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8">
      <div>
        <h1 className="font-sans text-2xl font-semibold text-ink">Publishing</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Which channels are connected, and which still need a platform connection built.
        </p>
      </div>

      {isLoading && <Skeleton className="h-32 w-full" />}

      {isError && (
        <EmptyState
          tone="error"
          title="Couldn't load strategies"
          description={error instanceof Error ? error.message : 'Something went wrong.'}
        />
      )}

      {strategies && strategies.length === 0 && (
        <EmptyState title="No strategies yet" description="Nothing to publish for yet." />
      )}

      {strategies?.map((strategy) => (
        <StrategyChannels key={strategy.slug} strategy={strategy} />
      ))}
    </div>
  );
}
