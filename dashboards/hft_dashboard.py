import dash
from dash import dcc, html, Input, Output, dash_table
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import sqlite3
from datetime import datetime

# Initialize Dash app
app = dash.Dash(__name__)

def load_market_groups():
    """
    Load unique markets grouped by token_id.
    Returns list of {label, value} dicts for dropdown.
    """
    conn = sqlite3.connect("hft_data.db")
    query = """
        SELECT 
            token_id,
            MIN(timestamp) as start_time,
            MAX(timestamp) as end_time,
            COUNT(*) as tick_count,
            AVG(strike_price) as strike
        FROM market_ticks
        GROUP BY token_id
        ORDER BY start_time DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    markets = []
    for _, row in df.iterrows():
        start = pd.to_datetime(row['start_time'])
        end = pd.to_datetime(row['end_time'])
        token_short = f"{row['token_id'][:8]}...{row['token_id'][-6:]}"
        
        label = f"{start.strftime('%b %d, %H:%M')} - {end.strftime('%H:%M')} UTC | Strike: ${row['strike']:.2f} | {row['tick_count']} ticks | {token_short}"
        
        markets.append({
            'label': label,
            'value': row['token_id']
        })
    
    return markets

def load_market_data(token_id):
    """Load tick data for a specific market"""
    conn = sqlite3.connect("hft_data.db")
    query = """
        SELECT 
            timestamp,
            strike_price,
            best_bid,
            best_ask,
            mid_price,
            oracle_price,
            minutes_until_close
        FROM market_ticks
        WHERE token_id = ?
        ORDER BY timestamp ASC
    """
    df = pd.read_sql_query(query, conn, params=(token_id,))
    conn.close()
    
    # Convert timestamp to datetime
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    return df

# Layout
app.layout = html.Div([
    html.H1("HFT Strategy Dashboard", style={'textAlign': 'center', 'marginBottom': 30}),
    
    html.Div([
        html.Label("Select Market:", style={'fontWeight': 'bold', 'fontSize': 16}),
        dcc.Dropdown(
            id='market-dropdown',
            options=load_market_groups(),
            value=None,
            placeholder="Select a market...",
            style={'width': '100%', 'marginBottom': 20}
        ),
    ], style={'padding': '20px'}),
    
    dcc.Graph(id='price-chart', style={'height': '700px'}),
    
    html.Div(id='market-stats', style={
        'padding': '20px',
        'backgroundColor': '#f0f0f0',
        'borderRadius': '5px',
        'marginTop': '20px',
        'marginBottom': '20px'
    }),
    
    html.Div([
        html.H3("Raw Data", style={'marginBottom': 10}),
        dash_table.DataTable(
            id='data-table',
            style_table={'overflowX': 'auto'},
            style_cell={
                'textAlign': 'left',
                'padding': '10px',
                'fontSize': 14
            },
            style_header={
                'backgroundColor': '#4CAF50',
                'color': 'white',
                'fontWeight': 'bold'
            },
            style_data={
                'backgroundColor': '#f9f9f9'
            },
            style_data_conditional=[
                {
                    'if': {'row_index': 'odd'},
                    'backgroundColor': '#ffffff'
                }
            ],
            page_size=100,  # ✅ Changed from 20 to 100 rows per page
            sort_action='native',
            filter_action='native'
        )
    ], style={'padding': '20px'})
])

@app.callback(
    [Output('price-chart', 'figure'),
     Output('market-stats', 'children'),
     Output('data-table', 'data'),
     Output('data-table', 'columns')],
    Input('market-dropdown', 'value')
)
def update_chart(token_id):
    if not token_id:
        # Empty chart
        fig = go.Figure()
        fig.add_annotation(
            text="Please select a market from the dropdown",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=20)
        )
        return fig, html.P("No market selected"), [], []
    
    # Load data
    df = load_market_data(token_id)
    
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available for this market",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=20)
        )
        return fig, html.P("No data found"), [], []
    
    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Add Oracle Price (left y-axis)
    fig.add_trace(
        go.Scatter(
            x=df['timestamp'],
            y=df['oracle_price'],
            mode='lines',
            name='Oracle Price (BTC)',
            line=dict(color='blue', width=2),
            hovertemplate='Oracle: $%{y:.2f}<extra></extra>'
        ),
        secondary_y=False
    )
    
    # Add Strike Price (left y-axis)
    fig.add_trace(
        go.Scatter(
            x=df['timestamp'],
            y=df['strike_price'],
            mode='lines',
            name='Strike Price',
            line=dict(color='red', width=2, dash='dash'),
            hovertemplate='Strike: $%{y:.2f}<extra></extra>'
        ),
        secondary_y=False
    )
    
    # Add Best Bid (right y-axis)
    fig.add_trace(
        go.Scatter(
            x=df['timestamp'],
            y=df['best_bid'],
            mode='lines',
            name='Best Bid',
            line=dict(color='green', width=1.5),
            hovertemplate='Bid: $%{y:.3f}<extra></extra>'
        ),
        secondary_y=True
    )
    
    # Add Best Ask (right y-axis)
    fig.add_trace(
        go.Scatter(
            x=df['timestamp'],
            y=df['best_ask'],
            mode='lines',
            name='Best Ask',
            line=dict(color='orange', width=1.5),
            hovertemplate='Ask: $%{y:.3f}<extra></extra>'
        ),
        secondary_y=True
    )
    
    # Update axes
    fig.update_xaxes(title_text="Time (UTC)")
    fig.update_yaxes(title_text="BTC Price (USD)", secondary_y=False)
    fig.update_yaxes(title_text="Polymarket Price", secondary_y=True)
    
    # Update layout
    fig.update_layout(
        title=f"Market Data: {df['timestamp'].min()} to {df['timestamp'].max()}",
        hovermode='x unified',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )
    
    # Calculate stats
    stats = html.Div([
        html.H3("Market Statistics"),
        html.P(f"Total Ticks: {len(df)}"),
        html.P(f"Strike Price: ${df['strike_price'].iloc[0]:.2f}"),
        html.P(f"Oracle Price Range: ${df['oracle_price'].min():.2f} - ${df['oracle_price'].max():.2f}"),
        html.P(f"Final Oracle Price: ${df['oracle_price'].iloc[-1]:.2f}"),
        html.P(f"Market Outcome: {'🟢 UP' if df['oracle_price'].iloc[-1] > df['strike_price'].iloc[0] else '🔴 DOWN'}"),
        html.P(f"Bid Range: ${df['best_bid'].min():.3f} - ${df['best_bid'].max():.3f}"),
        html.P(f"Ask Range: ${df['best_ask'].min():.3f} - ${df['best_ask'].max():.3f}"),
    ])
    
    # Prepare table data (round numeric columns for readability)
    df_display = df.copy()
    df_display['timestamp'] = df_display['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df_display['strike_price'] = df_display['strike_price'].round(2)
    df_display['best_bid'] = df_display['best_bid'].round(3)
    df_display['best_ask'] = df_display['best_ask'].round(3)
    df_display['mid_price'] = df_display['mid_price'].round(3)
    df_display['oracle_price'] = df_display['oracle_price'].round(2)
    df_display['minutes_until_close'] = df_display['minutes_until_close'].round(2)
    
    # Define table columns
    columns = [
        {"name": "Timestamp", "id": "timestamp"},
        {"name": "Strike Price", "id": "strike_price"},
        {"name": "Best Bid", "id": "best_bid"},
        {"name": "Best Ask", "id": "best_ask"},
        {"name": "Mid Price", "id": "mid_price"},
        {"name": "Oracle Price", "id": "oracle_price"},
        {"name": "Mins to Close", "id": "minutes_until_close"}
    ]
    
    table_data = df_display.to_dict('records')
    
    return fig, stats, table_data, columns

if __name__ == '__main__':
    app.run(debug=True, port=8050)