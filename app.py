from flask import Flask, render_template, request, jsonify
import os
from shopping_agent import MemoryAwareAgent  # Import your existing code

app = Flask(__name__)

# Global agent instance (in production, you'd want per-user agents)
agent = None

def get_agent():
    global agent
    if agent is None:
        user_id = "web_user"  # Simple single user for now
        agent = MemoryAwareAgent(user_id)
    return agent

@app.route('/')
def home():
    """Simple chat interface"""
    return render_template('chat.html')

@app.route('/send_message', methods=['POST'])
def send_message():
    """Handle message from frontend - this replaces your input() function"""
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return jsonify({'error': 'Empty message'})
        
        # This is where your input() function gets the text from
        agent = get_agent()
        response = agent.process_conversation(user_message)
        
        return jsonify({
            'response': response,
            'success': True
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'success': False
        })

if __name__ == '__main__':
    # Check for OpenAI API key
    if not os.getenv('OPENAI_API_KEY'):
        print("Warning: OPENAI_API_KEY not found in environment variables")
        exit(1)
    
    print("Starting web interface...")
    print("Open http://localhost:5000 in your browser")
    app.run(debug=True, host='0.0.0.0', port=5000)