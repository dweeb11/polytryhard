import { defineConfig } from 'vitest/config';
import path from 'node:path';

export default defineConfig({
	resolve: {
		alias: {
			$lib: path.resolve(__dirname, 'src/lib')
		}
	},
	test: {
		environment: 'node',
		setupFiles: ['src/lib/__tests__/setup.ts'],
		include: ['src/**/*.spec.ts']
	}
});
