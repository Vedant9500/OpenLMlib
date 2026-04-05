import React from 'react';
import { Box, Text } from 'ink';
import Spinner from 'ink-spinner';

function Progress({ steps }) {
  return React.createElement(Box, { flexDirection: 'column', padding: 1 },
    React.createElement(Text, { bold: true, color: 'cyan' }, 'Installing OpenLMlib'),
    React.createElement(Box, { flexDirection: 'column', marginTop: 1 },
      ...(steps || []).map((step, i) => {
        let icon;
        let color;
        if (step.status === 'running') {
          icon = React.createElement(Spinner, { type: 'dots' });
          color = 'yellow';
        } else if (step.status === 'done') {
          icon = React.createElement(Text, { color: 'green' }, '✔');
          color = 'green';
        } else if (step.status === 'error') {
          icon = React.createElement(Text, { color: 'red' }, '✖');
          color = 'red';
        } else {
          icon = React.createElement(Text, { color: 'gray' }, '·');
          color = 'gray';
        }

        return React.createElement(Box, { key: i },
          icon,
          React.createElement(Text, { color }, ` ${step.label}`),
        );
      })
    ),
  );
}

export default Progress;
