import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import ts from 'typescript-eslint';
import svelteConfig from './svelte.config.js';

export default ts.config(
	js.configs.recommended,
	...ts.configs.recommended,
	...svelte.configs['flat/recommended'],
	{
		languageOptions: {
			globals: { ...globals.browser, ...globals.node }
		}
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],
		languageOptions: {
			parserOptions: {
				parser: ts.parser,
				extraFileExtensions: ['.svelte'],
				svelteConfig
			}
		}
	},
	{
		rules: {
			'@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
			// Prototype pages intentionally render short static lists; add keys as data mutability increases.
			'svelte/require-each-key': 'off',
			// Prototype uses plain hrefs; adopt $app/paths resolve() when routing hardens.
			'svelte/no-navigation-without-resolve': 'off',
			// Map/Set in $derived.by and local UI state are intentional here.
			'svelte/prefer-svelte-reactivity': 'off'
		}
	},
	{ ignores: ['build/', '.svelte-kit/', 'node_modules/'] }
);
