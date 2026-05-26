<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { isDeveloperMode, setUiMode, uiMode, type UiMode } from '$lib/stores/uiMode';

	let { children } = $props();

	const sections = $derived(
		$isDeveloperMode
			? [
					{ href: '/settings/sources', label: 'Sources' },
					{ href: '/settings/plugins', label: 'Plugins' },
					{ href: '/settings/audit', label: 'Audit' }
				]
			: [
					{ href: '/settings/sources', label: 'Sources' },
					{ href: '/settings/plugins', label: 'Plugins' }
				]
	);

	$effect(() => {
		if (!$isDeveloperMode && $page.url.pathname.startsWith('/settings/audit')) {
			goto('/settings/sources');
		}
	});

	function isActive(href: string, pathname: string): boolean {
		return pathname === href || pathname.startsWith(`${href}/`);
	}

	function selectMode(mode: UiMode) {
		setUiMode(mode);
	}
</script>

<h1 class="mb-3 text-lg font-semibold text-slate-100">Settings</h1>

<section
	class="mb-6 rounded border border-[var(--color-border)] p-4"
	aria-labelledby="settings-display-mode-heading"
>
	<h2 id="settings-display-mode-heading" class="mb-1 text-sm font-medium text-slate-200">
		Display mode
	</h2>
	<p class="mb-3 text-xs text-slate-500">
		Developer mode shows prototype controls (env switcher, tick simulator, reset env, audit log).
		Release mode hides them for a cleaner operator view.
	</p>
	<div
		class="inline-flex rounded border border-[var(--color-border)] p-0.5 text-sm"
		role="group"
		aria-label="Display mode"
	>
		<button
			type="button"
			class="rounded px-3 py-1.5 {$uiMode === 'developer'
				? 'bg-slate-700 text-white'
				: 'text-slate-400 hover:text-slate-200'}"
			aria-pressed={$uiMode === 'developer'}
			onclick={() => selectMode('developer')}
		>
			Developer
		</button>
		<button
			type="button"
			class="rounded px-3 py-1.5 {$uiMode === 'release'
				? 'bg-slate-700 text-white'
				: 'text-slate-400 hover:text-slate-200'}"
			aria-pressed={$uiMode === 'release'}
			onclick={() => selectMode('release')}
		>
			Release
		</button>
	</div>
</section>

<nav class="mb-6 flex flex-wrap gap-1 border-b border-[var(--color-border)] pb-3" aria-label="Settings sections">
	{#each sections as section (section.href)}
		<a
			href={section.href}
			class="rounded px-3 py-1.5 text-sm {isActive(section.href, $page.url.pathname)
				? 'bg-slate-700 text-white'
				: 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}"
		>
			{section.label}
		</a>
	{/each}
</nav>
{@render children()}
