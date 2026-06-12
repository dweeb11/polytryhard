<script lang="ts">
	import {
		strategies,
		signals,
		sources,
		systemPaused,
		evalRoster,
		bankrollHistoryByStrategy
	} from '$lib/stores';
	import StateBadge from '$lib/components/StateBadge.svelte';
	import Sparkline from '$lib/components/Sparkline.svelte';
	import {
		compareIsoDesc,
		drawdownPct,
		formatCents,
		PAUSABLE_STATES,
		RESUMABLE_STATES,
		formatAge
	} from '$lib/utils';
	import { humanizeTicker, outcomeLabel, outcomeTone } from '$lib/humanize';
	import { strategyVerdict } from '$lib/humanize';
	import { isDeveloperMode } from '$lib/stores/uiMode';
	import { pauseStrategy, resumeStrategy, probeSource } from '$lib/actions';

	const STALE_SOURCE_MS = 60 * 60 * 1000;

	function fmtPct(v: number | null | undefined, digits = 1): string {
		return v == null ? '—' : `${(v * 100).toFixed(digits)}%`;
	}

	function fmtNum(v: number | null | undefined, digits = 3): string {
		return v == null ? '—' : v.toFixed(digits);
	}

	function signalTime(iso: string): string {
		const ms = Date.parse(iso);
		if (Number.isNaN(ms)) return '—';
		return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
	}

	function isToday(iso: string): boolean {
		const d = new Date(iso);
		const now = new Date();
		return d.toDateString() === now.toDateString();
	}

	const totalBankrollCents = $derived($strategies.reduce((sum, s) => sum + s.bankrollCents, 0));
	const pausedBankrollCents = $derived(
		$strategies
			.filter((s) => RESUMABLE_STATES.includes(s.state as (typeof RESUMABLE_STATES)[number]))
			.reduce((sum, s) => sum + s.bankrollCents, 0)
	);
	const todayPnlCents = $derived($strategies.reduce((sum, s) => sum + s.todayPnlCents, 0));

	const todaySignals = $derived($signals.filter((s) => isToday(s.evaluatedAt)));
	const todayCounts = $derived({
		placed: todaySignals.filter((s) => outcomeTone(s.outcome) === 'placed').length,
		skipped: todaySignals.filter((s) => outcomeTone(s.outcome) === 'skip').length,
		blocked: todaySignals.filter((s) => outcomeTone(s.outcome) === 'block').length
	});

	const provenEdges = $derived(
		Object.values($evalRoster).filter(
			(ev) => ev.posteriorEdgeCiLow != null && ev.posteriorEdgeCiLow > 0
		)
	);

	interface AttentionItem {
		severity: 'crit' | 'warn';
		tag: string;
		message: string;
		href: string;
		action: string;
	}

	const attention = $derived.by((): AttentionItem[] => {
		const items: AttentionItem[] = [];
		if ($systemPaused) {
			items.push({
				severity: 'crit',
				tag: 'kill switch',
				message: 'Kill switch is tripped — all executor actions blocked',
				href: '/',
				action: 'Resume from header'
			});
		}
		for (const s of $strategies) {
			if (RESUMABLE_STATES.includes(s.state as (typeof RESUMABLE_STATES)[number])) {
				items.push({
					severity: 'crit',
					tag: 'paused',
					message: `${s.name} — ${strategyVerdict(s, $evalRoster[s.name])} ${formatCents(s.bankrollCents)} idle`,
					href: `/strategies/${s.name}`,
					action: 'Review'
				});
			}
		}
		for (const src of $sources) {
			const fetchedMs = Date.parse(src.lastSuccessfulFetch);
			const stale = Number.isNaN(fetchedMs) || Date.now() - fetchedMs > STALE_SOURCE_MS;
			if (src.state !== 'healthy' || stale) {
				items.push({
					severity: src.state === 'down' ? 'crit' : 'warn',
					tag: src.state === 'healthy' ? 'stale' : src.state,
					message: `${src.displayName} — last fetch ${formatAge(src.lastSuccessfulFetch)}; dependent strategies fail closed`,
					href: '/settings/sources',
					action: 'Inspect'
				});
			}
		}
		return items;
	});

	const tapeSignals = $derived(
		[...todaySignals].sort((a, b) => compareIsoDesc(a.evaluatedAt, b.evaluatedAt)).slice(0, 14)
	);

	const toneClass: Record<string, string> = {
		placed: 'text-[var(--color-ok)]',
		skip: 'text-[var(--color-muted)]',
		block: 'text-[var(--color-warn)]'
	};

	function shortName(name: string): string {
		return name.replace(/^weather_/, '');
	}
</script>

<!-- Status strip -->
<section
	class="mb-6 grid grid-cols-2 overflow-hidden rounded-md border border-[var(--color-border)] bg-[var(--color-border)] gap-px lg:grid-cols-4"
>
	<div class="bg-[var(--color-panel)] px-5 py-4">
		<div class="mb-1.5 text-[10px] uppercase tracking-[0.14em] text-[var(--color-faint)]">
			Total bankroll
		</div>
		<div class="font-sans text-2xl font-bold tabular-nums text-[var(--color-heading)]">
			{formatCents(totalBankrollCents)}
		</div>
		<div class="mt-1 text-[11px] tabular-nums text-[var(--color-muted)]">
			across {$strategies.length} strategies{pausedBankrollCents > 0
				? ` · ${formatCents(pausedBankrollCents)} idle in paused`
				: ''}
		</div>
	</div>
	<div class="bg-[var(--color-panel)] px-5 py-4">
		<div class="mb-1.5 text-[10px] uppercase tracking-[0.14em] text-[var(--color-faint)]">
			Today
		</div>
		<div
			class="font-sans text-2xl font-bold tabular-nums {todayPnlCents >= 0
				? 'text-[var(--color-ok)]'
				: 'text-[var(--color-danger)]'}"
		>
			{todayPnlCents >= 0 ? '+' : ''}{formatCents(todayPnlCents)}
		</div>
		<div class="mt-1 text-[11px] tabular-nums text-[var(--color-muted)]">
			{todayCounts.placed} orders · {todayCounts.skipped} skips · {todayCounts.blocked} blocks
		</div>
	</div>
	<div class="bg-[var(--color-panel)] px-5 py-4">
		<div class="mb-1.5 text-[10px] uppercase tracking-[0.14em] text-[var(--color-faint)]">
			Proven edge
		</div>
		<div class="font-sans text-2xl font-bold tabular-nums text-[var(--color-heading)]">
			{provenEdges.length}<span class="text-sm text-[var(--color-muted)]">/{$strategies.length}</span>
		</div>
		<div class="mt-1 truncate text-[11px] tabular-nums text-[var(--color-muted)]">
			{#if provenEdges.length > 0}
				{shortName(provenEdges[0].strategyName)} CI-low
				<span class="text-[var(--color-ok)]">{fmtPct(provenEdges[0].posteriorEdgeCiLow)}</span>
			{:else}
				needs CI-low &gt; 0 to count
			{/if}
		</div>
	</div>
	<div class="bg-[var(--color-panel)] px-5 py-4">
		<div class="mb-1.5 text-[10px] uppercase tracking-[0.14em] text-[var(--color-faint)]">
			System
		</div>
		{#if $systemPaused}
			<div class="font-sans text-xl font-bold text-[var(--color-danger)]">■ PAUSED</div>
		{:else}
			<div class="font-sans text-xl font-bold text-[var(--color-accent)]">
				<span
					class="mr-1 inline-block h-2 w-2 animate-pulse rounded-full bg-[var(--color-accent)]"
				></span>TRADING
			</div>
		{/if}
		<div class="mt-1 text-[11px] text-[var(--color-muted)]">
			{#if attention.length > 0}
				<span class="text-[var(--color-warn)] tabular-nums">{attention.length}
					{attention.length === 1 ? 'item' : 'items'}</span>
				need attention ↓
			{:else}
				all clear
			{/if}
		</div>
	</div>
</section>

<!-- Attention queue -->
{#if attention.length > 0}
	<section
		class="mb-6 flex flex-col gap-2 rounded-md border border-[color-mix(in_srgb,var(--color-warn)_40%,transparent)] bg-[color-mix(in_srgb,var(--color-warn)_6%,transparent)] px-4 py-3"
	>
		{#each attention as item (item.tag + item.message)}
			<div class="flex items-baseline gap-3 text-[12.5px]">
				<span
					class="shrink-0 rounded px-1.5 py-px text-[10px] uppercase tracking-[0.1em] {item.severity ===
					'crit'
						? 'bg-[color-mix(in_srgb,var(--color-danger)_15%,transparent)] text-[var(--color-danger)]'
						: 'bg-[color-mix(in_srgb,var(--color-warn)_15%,transparent)] text-[var(--color-warn)]'}"
					>{item.tag}</span
				>
				<span class="min-w-0 text-[var(--color-bright)]">{item.message}</span>
				<a href={item.href} class="ml-auto shrink-0 text-[var(--color-cyan)] hover:underline"
					>{item.action} →</a
				>
			</div>
		{/each}
	</section>
{/if}

<!-- Strategy cards -->
<h2
	class="mb-3 flex items-center gap-2.5 text-[11px] uppercase tracking-[0.18em] text-[var(--color-faint)] after:h-px after:flex-1 after:bg-[var(--color-border)]"
>
	Strategies
</h2>
<section class="mb-7 grid gap-3.5 md:grid-cols-2 xl:grid-cols-3">
	{#each $strategies as s (s.name)}
		{@const ev = $evalRoster[s.name]}
		{@const dd = drawdownPct(s)}
		{@const paused = RESUMABLE_STATES.includes(s.state as (typeof RESUMABLE_STATES)[number])}
		{@const provenPos = ev?.posteriorEdgeCiLow != null && ev.posteriorEdgeCiLow > 0}
		<div
			class="relative overflow-hidden rounded-md border bg-[var(--color-panel)] p-4 transition-colors {paused
				? 'border-[color-mix(in_srgb,var(--color-warn)_40%,transparent)]'
				: 'border-[var(--color-border)] hover:border-[var(--color-border-bright)]'}"
		>
			<div
				class="absolute inset-x-0 top-0 h-0.5 {provenPos
					? 'bg-gradient-to-r from-[var(--color-ok)] to-transparent'
					: paused
						? 'bg-gradient-to-r from-[var(--color-danger)] to-transparent'
						: 'bg-gradient-to-r from-[var(--color-faint)] to-transparent'}"
			></div>
			<div class="mb-1 flex items-center justify-between gap-2">
				<a
					href="/strategies/{s.name}"
					class="truncate font-sans text-sm font-semibold text-[var(--color-heading)] hover:text-[var(--color-accent)]"
					>{s.name}</a
				>
				<StateBadge state={s.state} />
			</div>
			<p class="mb-3.5 min-h-8 text-[11.5px] leading-snug text-[var(--color-muted)]">
				{strategyVerdict(s, ev)}
			</p>
			<div class="flex items-end justify-between gap-2">
				<div>
					<div
						class="font-sans text-xl font-bold tabular-nums {paused
							? 'text-[var(--color-muted)]'
							: s.todayPnlCents >= 0
								? 'text-[var(--color-ok)]'
								: 'text-[var(--color-danger)]'}"
					>
						{s.todayPnlCents >= 0 ? '+' : ''}{formatCents(s.todayPnlCents)}
					</div>
					<div class="mt-0.5 text-[9.5px] uppercase tracking-[0.12em] text-[var(--color-faint)]">
						today{paused ? ' (paused)' : ''}
					</div>
				</div>
				<Sparkline
					points={$bankrollHistoryByStrategy[s.name] ?? []}
					tone={paused ? 'danger' : s.todayPnlCents >= 0 ? 'ok' : 'muted'}
				/>
			</div>
			<div
				class="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-[var(--color-border)] pt-2.5 text-[10.5px] tabular-nums text-[var(--color-muted)]"
			>
				<span>bank <b class="font-medium text-[var(--color-bright)]">{formatCents(s.bankrollCents)}</b></span>
				<span
					>edge
					<b
						class="font-medium {provenPos
							? 'text-[var(--color-ok)]'
							: ev?.posteriorEdgeCiLow != null && ev.posteriorEdgeCiLow < -0.02
								? 'text-[var(--color-danger)]'
								: 'text-[var(--color-bright)]'}">{fmtPct(ev?.posteriorEdgeCiLow)}</b
					></span
				>
				<span>brier <b class="font-medium text-[var(--color-bright)]">{fmtNum(ev?.brierScore)}</b></span>
				<span
					>dd
					<b
						class="font-medium {dd >= s.config.maxDrawdownPctFromHwm
							? 'text-[var(--color-danger)]'
							: 'text-[var(--color-bright)]'}">{dd.toFixed(1)}%</b
					></span
				>
				{#if PAUSABLE_STATES.includes(s.state as (typeof PAUSABLE_STATES)[number])}
					<button
						type="button"
						class="ml-auto text-[var(--color-warn)] hover:underline disabled:opacity-40"
						disabled={$systemPaused}
						title={$systemPaused ? 'Kill switch active' : 'Pause strategy'}
						onclick={() => void pauseStrategy(s.name, 'operator pause from overview')}
					>
						Pause
					</button>
				{:else if paused}
					<button
						type="button"
						class="ml-auto text-[var(--color-ok)] hover:underline disabled:opacity-40"
						disabled={$systemPaused}
						onclick={() => void resumeStrategy(s.name, 'operator resume from overview')}
					>
						Resume
					</button>
				{/if}
			</div>
		</div>
	{/each}
</section>

<!-- Signal tape + sources -->
<section class="grid gap-3.5 lg:grid-cols-[1.6fr_1fr]">
	<div class="rounded-md border border-[var(--color-border)] bg-[var(--color-panel)] p-4">
		<h2
			class="mb-2 flex items-center gap-2.5 text-[11px] uppercase tracking-[0.18em] text-[var(--color-faint)] after:h-px after:flex-1 after:bg-[var(--color-border)]"
		>
			Signal tape — today
		</h2>
		{#each tapeSignals as sig (sig.id)}
			<div
				class="grid grid-cols-[44px_1fr_auto] items-baseline gap-3 border-b border-[var(--color-border)] py-1.5 text-xs last:border-0"
			>
				<span class="text-[11px] tabular-nums text-[var(--color-faint)]">{signalTime(sig.evaluatedAt)}</span>
				<span class="min-w-0 truncate text-[var(--color-bright)]"
					><span class="text-[var(--color-purple)]">{shortName(sig.strategyName)}</span>
					· {humanizeTicker(sig.ticker)} · saw {(sig.probYes * 100).toFixed(0)}%</span
				>
				<span class="text-[11px] {toneClass[outcomeTone(sig.outcome)]}">{outcomeLabel(sig.outcome)}</span>
			</div>
		{:else}
			<p class="py-2 text-xs text-[var(--color-faint)]">No signals yet today.</p>
		{/each}
	</div>

	<div class="rounded-md border border-[var(--color-border)] bg-[var(--color-panel)] p-4">
		<h2
			class="mb-2 flex items-center gap-2.5 text-[11px] uppercase tracking-[0.18em] text-[var(--color-faint)] after:h-px after:flex-1 after:bg-[var(--color-border)]"
		>
			Data sources
		</h2>
		{#each $sources as src (src.name)}
			{@const stale =
				Number.isNaN(Date.parse(src.lastSuccessfulFetch)) ||
				Date.now() - Date.parse(src.lastSuccessfulFetch) > STALE_SOURCE_MS}
			<div
				class="flex items-center gap-2.5 border-b border-[var(--color-border)] py-2 text-xs last:border-0"
			>
				<span
					class="h-1.5 w-1.5 shrink-0 rounded-full {src.state === 'healthy'
						? 'bg-[var(--color-ok)]'
						: src.state === 'degraded'
							? 'bg-[var(--color-warn)]'
							: 'bg-[var(--color-danger)]'}"
				></span>
				<span class="truncate text-[var(--color-bright)]">{src.displayName}</span>
				<span
					class="ml-auto shrink-0 text-[11px] tabular-nums {stale
						? 'text-[var(--color-warn)]'
						: 'text-[var(--color-faint)]'}">{formatAge(src.lastSuccessfulFetch)}</span
				>
				{#if $isDeveloperMode}
					<button
						type="button"
						class="shrink-0 rounded border border-[var(--color-border)] px-2 py-0.5 text-[11px] text-[var(--color-muted)] hover:bg-[var(--color-panel-2)]"
						onclick={() => probeSource(src.name)}
					>
						Probe
					</button>
				{/if}
			</div>
		{/each}
	</div>
</section>
