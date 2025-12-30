#!/usr/bin/env python3
"""
Plot PV power, battery SOC, and cell temperature from LuxPower inverter data.
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import sys

def load_data(filename):
    """Load CSV data and parse timestamps."""
    df = pd.read_csv(filename)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

def create_plot(df, output_file='power_plot.png'):
    """Create a four-panel plot with PV power, output power, SOC, and cell temperature."""

    # Set up the figure with four subplots sharing x-axis
    fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(12, 12), sharex=True)
    fig.suptitle('LuxPower Inverter Data', fontsize=14, fontweight='bold')

    # Color scheme
    colors = {
        'pv1': '#FF6B35',      # Orange
        'pv2': '#004E89',      # Blue
        'discharge': '#9932CC', # Dark orchid (purple)
        'soc': '#2E8B57',      # Sea green
        'temp_max': '#DC143C', # Crimson
        'temp_min': '#4169E1', # Royal blue
    }

    # Plot 1: PV Power
    ax1.fill_between(df['timestamp'], df['ppv1_w'], alpha=0.3, color=colors['pv1'])
    ax1.fill_between(df['timestamp'], df['ppv2_w'], alpha=0.3, color=colors['pv2'])
    ax1.plot(df['timestamp'], df['ppv1_w'], color=colors['pv1'], linewidth=1.5, label='PV1 Power')
    ax1.plot(df['timestamp'], df['ppv2_w'], color=colors['pv2'], linewidth=1.5, label='PV2 Power')
    ax1.set_ylabel('Power (W)', fontsize=11)
    ax1.legend(loc='upper right', framealpha=0.9)
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(bottom=0)

    # Plot 2: Output Power (Discharge)
    ax2.fill_between(df['timestamp'], df['p_discharge_w'], alpha=0.3, color=colors['discharge'])
    ax2.plot(df['timestamp'], df['p_discharge_w'], color=colors['discharge'], linewidth=1.5, label='Output Power')
    ax2.set_ylabel('Power (W)', fontsize=11)
    ax2.legend(loc='upper right', framealpha=0.9)
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(bottom=0)

    # Plot 3: Battery SOC
    ax3.fill_between(df['timestamp'], df['soc_pct'], alpha=0.3, color=colors['soc'])
    ax3.plot(df['timestamp'], df['soc_pct'], color=colors['soc'], linewidth=2, label='Battery SOC')
    ax3.set_ylabel('SOC (%)', fontsize=11)
    ax3.legend(loc='upper right', framealpha=0.9)
    ax3.grid(True, alpha=0.3)
    ax3.set_ylim(0, 100)

    # Plot 4: Cell Temperature
    ax4.fill_between(df['timestamp'], df['min_cell_temp_c'], df['max_cell_temp_c'],
                     alpha=0.3, color='#808080', label='Temp Range')
    ax4.plot(df['timestamp'], df['max_cell_temp_c'], color=colors['temp_max'],
             linewidth=1.5, label='Max Cell Temp')
    ax4.plot(df['timestamp'], df['min_cell_temp_c'], color=colors['temp_min'],
             linewidth=1.5, label='Min Cell Temp')
    ax4.set_ylabel('Temperature (°C)', fontsize=11)
    ax4.set_xlabel('Time', fontsize=11)
    ax4.legend(loc='upper right', framealpha=0.9)
    ax4.grid(True, alpha=0.3)

    # Format x-axis
    ax4.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax4.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    plt.xticks(rotation=45, ha='right')

    # Add date range to title
    start_date = df['timestamp'].min().strftime('%Y-%m-%d %H:%M')
    end_date = df['timestamp'].max().strftime('%Y-%m-%d %H:%M')
    fig.text(0.5, 0.95, f'{start_date} to {end_date}', ha='center', fontsize=10, style='italic')

    # Adjust layout
    plt.tight_layout()
    plt.subplots_adjust(top=0.93)

    # Save the plot
    plt.savefig(output_file, dpi=150, bbox_inches='tight', facecolor='white', edgecolor='none')
    print(f'Plot saved to {output_file}')

    return fig

def main():
    # Default input/output files
    input_file = 'data_dec28.csv'
    output_file = 'power_plot.png'

    # Allow command line arguments
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_file = sys.argv[2]

    print(f'Loading data from {input_file}...')
    df = load_data(input_file)
    print(f'Loaded {len(df)} data points')

    print('Creating plot...')
    create_plot(df, output_file)

if __name__ == '__main__':
    main()
