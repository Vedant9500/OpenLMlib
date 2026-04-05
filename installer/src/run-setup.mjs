#!/usr/bin/env node

import React from 'react';
import { render } from 'ink';
import chalk from 'chalk';
import SetupWizard from './ui/setup-wizard.js';

if (!process.stdin.isTTY) {
  console.log('');
  console.log(chalk.cyan('    ███████    ███████████  ██████████ ██████   █████ █████       ██████   ██████ █████       █████ ███████████'));
  console.log(chalk.cyan('  ███░░░░░███ ░░███░░░░░███░░███░░░░░█░░██████ ░░███ ░░███       ░░██████ ██████ ░░███       ░░███ ░░███░░░░░███'));
  console.log(chalk.cyan(' ███     ░░███ ░███    ░███ ░███  █ ░  ░███░███ ░███  ░███        ░███░█████░███  ░███        ░███  ░███    ░███'));
  console.log(chalk.cyan('░███      ░███ ░██████████  ░██████    ░███░░███░███  ░███        ░███░░███ ░███  ░███        ░███  ░██████████'));
  console.log(chalk.cyan('░███      ░███ ░███░░░░░░   ░███░░█    ░███ ░░██████  ░███        ░███ ░░░  ░███  ░███        ░███  ░███░░░░░███'));
  console.log(chalk.cyan('░░███     ███  ░███         ░███ ░   █ ░███  ░░█████  ░███      █ ░███      ░███  ░███      █ ░███  ░███    ░███'));
  console.log(chalk.cyan(' ░░░███████░   █████        ██████████ █████  ░░█████ ███████████ █████     █████ ███████████ █████ ███████████'));
  console.log(chalk.cyan('   ░░░░░░░    ░░░░░        ░░░░░░░░░░ ░░░░░    ░░░░░ ░░░░░░░░░░░ ░░░░░     ░░░░░ ░░░░░░░░░░░ ░░░░░ ░░░░░░░░░░░'));
  console.log('');
  console.log(chalk.bold('  Setup Wizard'));
  console.log('');
  console.log(chalk.yellow('  The interactive setup requires a terminal.'));
  console.log(chalk.gray('  Run this command directly in your terminal:'));
  console.log('');
  console.log(chalk.white('    openlmlib setup'));
  console.log('');
  process.exit(1);
}

render(React.createElement(SetupWizard));
