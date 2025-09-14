import json
import os
from datetime import datetime
from typing import Dict, Any, List  # Added missing List import
from crewai import Agent, Task, Crew, Process
from crewai.tools import tool
import requests

CART_DIR = "cart_data"
os.makedirs(CART_DIR, exist_ok=True)

ORDER_URL = f"{{BASE_URL}}/webhook/c619c80d-144d-442a-ac1f-9d898a169950"
BASE_URL = os.getenv('base_url')

class OrderUploader:
    def __init__(self, cart_file="cart.json"):
        self.cart_file = cart_file
        self.order_url = f"{{BASE_URL}}/webhook/c619c80d-144d-442a-ac1f-9d898a169950"

    def upload_cart(self):
        # 1. Check if cart file exists
        if not os.path.exists(self.cart_file):
            return {"success": False, "error": "Cart file not found."}

        try:
            # 2. Load cart JSON
            with open(self.cart_file, 'r') as f:
                cart_data = json.load(f)

            # 3. Upload to webhook
            headers = {
                "Content-Type": "application/json"
            }
            response = requests.post(self.order_url, headers=headers, json=cart_data)
            response.raise_for_status()

            return {
                "success": True,
                "status_code": response.status_code,
                "response": response.json()
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


class CartManager:
    """
    In-memory cart storage for the session.
    In production, you might want to use Redis, database, or file storage.
    """

    def __init__(self, user_id: str, memory_dir: str = 'convo_data'):
        self.user_id = user_id
        self.memory_dir = memory_dir
        self.cart_file = os.path.join(memory_dir, f"{user_id}_cart.json")
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        # Create memory directory if it doesn't exist
        os.makedirs(memory_dir, exist_ok=True)
        self.cart = self.load_cart()

    def load_cart(self):
        if os.path.exists(self.cart_file):
            try:
                with open(self.cart_file, 'r') as f:
                    cart = json.load(f)
                    if cart.get('cart_id'):
                        return cart
            except (json.JSONDecodeError, KeyError):
                pass  # fallback to creating new cart

        # If no valid cart file, create a new one from API
        url = "{{BASE_URL}}/webhook/9f33ff38-4efe-4bca-ab0a-1454a1d89bb3"
        headers = {
            'Content-Type': "application/json",
            'x-publishable-api-key': os.getenv('x-publishable-api-key')
        }
        try:
            response = requests.post(url, headers=headers)
            response.raise_for_status()
            response_data = response.json()

            cart_id = response_data["cart"]["id"]

            cart = {"cart_id": cart_id, "items": []}

            # Save cart locally
            with open(self.cart_file, 'w') as f:
                json.dump(cart, f)
            return cart
        except Exception as e:
            return {"cart_id": "", "items": [], "error": str(e)}

    def save_cart(self):
        with open(self.cart_file, 'w') as f:
            json.dump(self.cart, f, indent=2)

    @property
    def items(self):
        return self.cart.get("items", [])

    @items.setter
    def items(self, new_items):
        self.cart["items"] = new_items

    def add_item(self, variant_id: str, quantity: int, product_info: Dict[str, Any]) -> Dict[str, Any]:
        """Add item to cart or update quantity if already exists"""
        existing_item = None
        for item in self.items:
            if item['variant_id'] == variant_id:
                existing_item = item
                break

        if existing_item:
            # Update existing item quantity
            existing_item['quantity'] += quantity
            existing_item['subtotal'] = existing_item['price'] * existing_item['quantity']
            existing_item['updated_at'] = datetime.now().isoformat()
            action_performed = f"Updated {product_info['name']} quantity to {existing_item['quantity']}"
        else:
            # Add new item
            cart_item = {
                'variant_id': variant_id,
                'product_name': product_info['name'],
                'price': product_info['price'],
                'quantity': quantity,
                'subtotal': product_info['price'] * quantity,
                'added_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            self.items.append(cart_item)
            action_performed = f"Added {quantity} {product_info['name']} to cart"

        self.updated_at = datetime.now()
        self.save_cart()

        return {
            'success': True,
            'action': action_performed,
            'cart_summary': self._get_cart_summary()
        }

    def remove_item(self, variant_id: str) -> Dict[str, Any]:
        removed_item = None
        original_count = len(self.items)

        # Find and remove the item
        new_items = []
        for item in self.items:
            if item['variant_id'] == variant_id and removed_item is None:
                removed_item = item
            else:
                new_items.append(item)

        self.items = new_items

        if removed_item:
            self.updated_at = datetime.now()
            self.save_cart()
            return {
                'success': True,
                'action': f"Removed {removed_item['product_name']} from cart",
                'cart_summary': self._get_cart_summary()
            }
        else:
            return {
                'success': False,
                'error': f"Item with variant_id {variant_id} not found in cart"
            }

    def update_quantity(self, variant_id: str, new_quantity: int) -> Dict[str, Any]:
        """Update item quantity (set to specific amount)"""
        if new_quantity <= 0:
            return self.remove_item(variant_id)

        for item in self.items:
            if item['variant_id'] == variant_id:
                old_quantity = item['quantity']
                item['quantity'] = new_quantity
                item['subtotal'] = item['price'] * new_quantity
                item['updated_at'] = datetime.now().isoformat()
                self.updated_at = datetime.now()
                self.save_cart()

                return {
                    'success': True,
                    'action': f"Updated {item['product_name']} quantity from {old_quantity} to {new_quantity}",
                    'cart_summary': self._get_cart_summary()
                }

        return {
            'success': False,
            'error': f"Item with variant_id {variant_id} not found in cart"
        }

    def view_cart(self) -> Dict[str, Any]:
        """Get current cart contents"""
        if not self.items:
            return {
                'success': True,
                'cart_empty': True,
                'message': "Your cart is currently empty",
                'total_items': 0,
                'total_amount': 0.0
            }

        return {
            'success': True,
            'cart_empty': False,
            'items': self.items.copy(),
            'cart_summary': self._get_cart_summary(),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    def clear_cart(self) -> Dict[str, Any]:
        """Clear all items from cart"""
        items_count = len(self.items)
        self.items.clear()
        self.updated_at = datetime.now()
        self.save_cart()

        return {
            'success': True,
            'action': f"Cleared cart ({items_count} items removed)",
            'cart_summary': self._get_cart_summary()
        }

    def get_cart_for_order(self) -> Dict[str, Any]:
        """Get cart data formatted for order creation"""
        if not self.items:
            return {
                'success': False,
                'error': "Cannot create order from empty cart"
            }

        order_data = {
            'items': [],
            'summary': self._get_cart_summary(),
            'cart_created_at': self.created_at.isoformat(),
            'cart_updated_at': self.updated_at.isoformat()
        }

        for item in self.items:
            order_item = {
                'variant_id': item['variant_id'],
                'product_name': item['product_name'],
                'price': item['price'],
                'quantity': item['quantity'],
                'subtotal': item['subtotal']
            }
            order_data['items'].append(order_item)

        return {
            'success': True,
            'order_data': order_data
        }

    def _get_cart_summary(self) -> Dict[str, Any]:
        """Generate cart summary with totals"""
        if not self.items:
            return {
                'total_items': 0,
                'total_quantity': 0,
                'total_amount': 0.0,
                'currency': '₹'
            }

        total_items = len(self.items)
        total_quantity = sum(item['quantity'] for item in self.items)
        total_amount = sum(item['subtotal'] for item in self.items)

        return {
            'total_items': total_items,
            'total_quantity': total_quantity,
            'total_amount': round(total_amount, 2),
            'currency': '₹'
        }


class PersistentCartManager:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.cart_file = os.path.join(CART_DIR, f"{user_id}_cart.json")
        self.cart = CartManager(user_id)
        self.load_cart()

    def save_cart(self):
        with open(self.cart_file, 'w') as f:
            json.dump(self.cart.view_cart(), f, indent=2)

    def load_cart(self):
        if os.path.exists(self.cart_file):
            try:
                with open(self.cart_file, 'r') as f:
                    data = json.load(f)
                    # Load items into CartManager
                    if hasattr(self.cart, 'cart_items'):
                        self.cart.cart_items = data.get("items", [])
                    else:
                        self.cart.cart["items"] = data.get("items", [])
                    self.cart.created_at = datetime.fromisoformat(data.get("created_at", datetime.now().isoformat()))
                    self.cart.updated_at = datetime.fromisoformat(data.get("updated_at", datetime.now().isoformat()))
            except:
                pass


class PersistentMemoryManager:
    """This class is responsible for maintaining conversation history"""

    def __init__(self, user_id: str, memory_dir: str = 'convo_data'):
        self.user_id = user_id
        self.memory_dir = memory_dir
        self.conversation_file = os.path.join(memory_dir, f"{user_id}_conversation.json")

        # Create directory holding conversation data if it doesn't exist
        os.makedirs(memory_dir, exist_ok=True)

        # Load existing chat history and memory data
        self.conversations = self.load_conversations()

    def load_conversations(self) -> List:
        """Load conversation history from file"""
        if os.path.exists(self.conversation_file):
            try:
                with open(self.conversation_file, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []

    def save_conversation(self):
        """Save conversation history to file"""
        with open(self.conversation_file, 'w') as f:
            json.dump(self.conversations, f, indent=2)

    def add_conversation(self, user_input: str, agent_response: str):
        """Add conversation turn to memory"""
        conversation_entry = {
            "timestamp": datetime.now().isoformat(),
            "user_input": user_input,
            "agent_response": agent_response
        }

        self.conversations.append(conversation_entry)

        if len(self.conversations) > 50:
            self.conversations = self.conversations[-50:]

        self.save_conversation()

    def get_memory_context(self) -> str:
        """Get formatted memory context for agents"""
        context = f"=== MEMORY ABOUT {self.user_id.upper()} ===\n"
        # Add recent conversations
        if self.conversations:
            context += "RECENT CONVERSATION HISTORY:\n"
            recent_conversations = self.conversations[-3:] if len(self.conversations) >= 3 else self.conversations
            for i, conv in enumerate(recent_conversations, 1):
                context += f"{i}. User: {conv['user_input']}\n"
                context += f"   Assistant: {conv['agent_response'][:150]}...\n"
            context += "\n"

        context += "=== END OF MEMORY ===\n"
        return context


class MemoryAwareAgent:
    """Crew AI agent with persistent memory capabilities using manager_agent approach"""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.memory_manager = PersistentMemoryManager(user_id)
        self.cart_manager = PersistentCartManager(user_id)
        self.setup_agents()

    def setup_agents(self):
        """Setup Crew AI agents with memory context - manager_agent approach"""

        @tool("fetch_catalog")
        def fetch_catalog():
            """Fetch the product catalog from the API endpoint"""
            try:
                response = requests.get("{{BASE_URL}}/webhook/5098b292-ff46-4f5a-bd04-6708407952dc")
                if response.status_code == 200:
                    data = response.json()
                    return json.dumps(data, indent=2)
                else:
                    return f"Request failed with status code: {response.status_code}"
            except Exception as e:
                return f"Error fetching catalog: {str(e)}"

        @tool("cart_tool")
        def cart_tool(action: str, variant_id: str = None, quantity: int = None,
                      product_info: Dict[str, Any] = None):
            """
            Tool to manipulate the user's cart.
            Actions supported: add, remove, update, view, clear.
            """
            if action == "add":
                result = self.cart_manager.cart.add_item(variant_id, quantity, product_info)
            elif action == "remove":
                result = self.cart_manager.cart.remove_item(variant_id)
            elif action == "update":
                result = self.cart_manager.cart.update_quantity(variant_id, quantity)
            elif action == "view":
                result = self.cart_manager.cart.view_cart()
            elif action == "clear":
                result = self.cart_manager.cart.clear_cart()
            else:
                result = {"success": False, "error": f"Unknown action: {action}"}

            self.cart_manager.save_cart()  # Persist after every change
            return json.dumps(result, indent=2)

        @tool("create_order")
        def create_order():
            """Uploads the current cart JSON file to the order webhook."""
            try:
                with open(self.cart_manager.cart_file, "r") as f:
                    cart_data = json.load(f)

                response = requests.post(
                    "{{BASE_URL}}/webhook/c619c80d-144d-442a-ac1f-9d898a169950",
                    json=cart_data
                )
                response.raise_for_status()
                return {"success": True, "response": response.json()}
            except Exception as e:
                return {"success": False, "error": str(e)}

        self.router_agent = Agent(
            role="Intent Router",
            goal="Decide whether the user wants to browse products or place an order, then route them accordingly.",
            backstory=(
                "You are the first point of contact. Your job is to analyze the user's latest message and decide:\n"
                "- If the user asks about categories, products, or browsing → send to Browsing Agent.\n"
                "- If the user mentions a product name and possibly quantity → send to Order Agent.\n"
                "- Always respond naturally, not in JSON or technical terms.\n"
            ),
            verbose=True,
            allow_delegation=True,
        )

        # Browsing Agent
        self.browsing_agent = Agent(
            role="Product Catalog Guide",
            goal="Help the user explore available product categories and browse products without overwhelming them.",
            backstory=(
                "You are a friendly shopping assistant who guides users through the catalog. "
                "You never show raw IDs like variant_id, and you present only the product name and price. "
                "Always try to understand user intent, then show category list or product list belonging to particular category. "
                "You keep the tone natural, conversational, and avoid hallucinations by only relying on the catalog tool."
                "You MUST use the 'fetch_catalog' tool to get the real catalog data."
            ),
            verbose=True,
            allow_delegation=False,
            tools=[fetch_catalog]
        )

        self.order_agent = Agent(
            role="Order Placement Assistant",
            goal="Manage user's shopping cart, verify product availability, and handle order placement efficiently",
            backstory="""You are an experienced order management assistant who helps customers 
            build their shopping cart and place orders. You have access to the product catalog 
            and can add items to cart, show cart contents, and process checkout.

            Key responsibilities:
            - Always verify product exists in catalog before adding to cart
            - Never expose internal variant_id or technical details to users
            - Keep cart persistent until checkout is completed
            - Always confirm with user before finalizing any order
            - Provide clear, friendly responses about cart status
            - ADD vs UPDATE decision:
            - For SET requests, call cart_tool(action="update", variant_id=..., quantity=X)
            - For INCREMENT requests, call cart_tool(action="add", variant_id=..., quantity=X)""",

            tools=[fetch_catalog, cart_tool, create_order],
            verbose=True,
            allow_delegation=False,
            max_iter=3

        )

    def process_conversation(self, user_input: str) -> str:
        """Process user input using manager_agent approach with memory integration"""

        memory_context = self.memory_manager.get_memory_context()

        router_task = Task(
            description=(
                f"Analyze user input: '{user_input}'\n\n"
                "ROUTING DECISIONS:\n"
                "🔍 Route to BROWSING if user wants to:\n"
                "- Explore categories or browse products\n"
                "- Ask 'what do you have?' or similar discovery questions\n"
                "- Request specific category items\n\n"
                "🛒 Route to ORDERING if user wants to:\n"
                "- Add specific products to cart (with quantity)\n"
                "- View/modify cart contents\n"
                "- Proceed to checkout\n"
                "- Buy/order/purchase something specific\n\n"
                "Make the routing decision quickly and delegate to the appropriate specialist."
            ),
            expected_output="User successfully routed to either browsing or ordering specialist based on clear intent analysis.",
            agent=self.router_agent,
        )

        browsing_task = Task(
            description=(
                f"USER REQUEST: {user_input}\n"
                f"CONVERSATION CONTEXT: {memory_context}\n\n"
                "MISSION: Help user discover products through intelligent browsing\n\n"
                "WORKFLOW:\n"
                "1. 📊 FETCH DATA: Use fetch_catalog to get latest product data\n"
                "2. 🎯 UNDERSTAND INTENT:\n"
                "   - General browsing → Show categories\n"
                "   - Category request → Show products in that category\n"
                "   - Product inquiry → Provide specific details\n"
                "3. 📋 PRESENT CLEANLY:\n"
                "   - Group by categories when appropriate\n"
                "   - Show: Product name, price in ₹ format\n"
                "   - Hide: variant_ids, technical data\n"
                "4. 🔄 GUIDE NEXT STEPS:\n"
                "   - Suggest specific products they might like\n"
                "   - If they show interest in buying, prompt for quantity\n\n"
                "CATALOG PARSING:\n"
                "- Data structure: [{'data': [{'variant_id': '...', 'product_name': '...', 'price': X, 'category': '...'}]}]\n"
                "- Extract products from: response[0]['data']\n"
                "- Group by 'category' field for organized display"
            ),
            expected_output="""Clean, organized product presentation:

            CATEGORY VIEW EXAMPLE:
            "🛍️ Our Product Categories:
            🍞 Bread (3 items)
            🍪 Cookies (1 item) 
            🍦 Ice cream (3 items)

            Which category would you like to explore?"

            PRODUCT VIEW EXAMPLE:
            "🍞 Bread Products:
            • Brown bread - ₹45
            • White bread - ₹25
            • Burger Buns - ₹50

            Any of these catch your interest? Just let me know how many you'd like!"

            Always end with engaging question to continue conversation.""",
            agent=self.browsing_agent,
        )

        order_task = Task(
            description=(
                f"USER REQUEST: {user_input}\n"
                f"CONVERSATION CONTEXT: {memory_context}\n\n"
                "MISSION: Process orders with 100% accuracy and excellent customer experience\n\n"
                "CRITICAL WORKFLOW:\n"
                "1. 🔍 PRODUCT VERIFICATION:\n"
                "   - Use fetch_catalog to get current product data\n"
                "   - Parse structure: catalog[0]['data'] contains product array\n"
                "   - Match user's product name (case-insensitive)\n"
                "   - Extract correct variant_id from matched product\n\n"
                "2. 🛒 CART OPERATIONS:\n"
                "   - ADD: cart_tool(action='add', variant_id=VERIFIED_ID, quantity=X, product_info={'name': EXACT_NAME, 'price': EXACT_PRICE})\n"
                "   - VIEW: cart_tool(action='view')\n"
                "   - UPDATE: cart_tool(action='update', variant_id=ID, quantity=NEW_QTY)\n"
                "   - REMOVE: cart_tool(action='remove', variant_id=ID)\n\n"
                "3. ✅ ORDER PROCESSING:\n"
                "   - Show cart summary before checkout\n"
                "   - Get explicit confirmation: 'Ready to place order?'\n"
                "   - Use create_order() only after confirmation\n"
                "   - Clear cart after successful order\n\n"
                "VARIANT_ID EXTRACTION EXAMPLE:\n"
                "```\n"
                "catalog_response = fetch_catalog()\n"
                "products = catalog_response[0]['data']\n"
                "for product in products:\n"
                "    if 'brown bread' in product['product_name'].lower():\n"
                "        correct_variant_id = product['variant_id']  # USE THIS!\n"
                "        price = product['price']\n"
                "        break\n"
                "```\n\n"
                "ERROR PREVENTION:\n"
                "❌ NEVER hardcode variant_ids\n"
                "❌ NEVER skip product verification\n"
                "✅ ALWAYS match against live catalog data\n"
                "✅ ALWAYS use exact variant_id from catalog\n"
                "✅ ALWAYS show clear totals and confirmations"
                """INTENT DETECTION RULES:
                - If the user says “I want X …”, “Give me X …”, “I’ll take X …” → treat as SET QUANTITY (replace with X, not add).
                - If the user says “Add X more …”, “Increase by X …” -“Another X …” → treat as INCREMENT(add to existing)."
                - If the user says “Change to X …”, “Update to X …” → use UPDATE action."""
            ),
            expected_output="""Precise order processing with clear confirmations:

            ADD TO CART EXAMPLE:
            "✅ Added 2 Brown bread (₹45 each) to your cart!

            🛒 Cart Summary:
            • Brown bread × 2 = ₹90

            Total: ₹90

            Would you like to add more items or proceed to checkout?"

            CHECKOUT EXAMPLE:
            "🛒 Order Summary:
            • Brown bread × 2 = ₹90
            • Chocholate cookies × 1 = ₹170

            Total: ₹260

            Ready to place your order? (Type 'yes' to confirm)"

            Always show clear totals, ask for confirmation, and guide next steps.""",
            agent=self.order_agent,
        )

        # Create crew with manager_agent approach
        crew = Crew(
            agents=[self.browsing_agent, self.order_agent],
            tasks=[browsing_task, order_task],
            verbose=False,
            process=Process.hierarchical,
            manager_agent=self.router_agent
        )

        try:
            result = crew.kickoff()
            response = str(result)

            # Store conversation in memory
            self.memory_manager.add_conversation(user_input, response)

            return response

        except Exception as e:
            print(f"Error in conversation processing: {e}")
            return "I'm sorry, I encountered an error processing your message. Please try again."

    def clear_memory(self):
        """Clear conversation memory"""
        self.memory_manager.conversations = []
        self.memory_manager.save_conversation()


class ConversationInterface:
    """Interactive conversation interface"""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.agent = MemoryAwareAgent(user_id)
        print(f"Starting conversation interface for user: {user_id}")
        print("Type 'quit' to exit, 'clear' to clear memory")

    def start_conversation(self):
        """Start interactive conversation loop"""

        # Show existing memory if any
        if self.agent.memory_manager.conversations:
            print(
                f"\nWelcome back! I have {len(self.agent.memory_manager.conversations)} previous conversations with you.")

        while True:
            try:
                user_input = input(f"\n{self.user_id}: ").strip()

                if user_input.lower() == 'quit':
                    print("Goodbye!")
                    break
                elif user_input.lower() == 'clear':
                    self.agent.clear_memory()
                    print("Memory cleared!")
                    continue
                elif not user_input:
                    continue

                # Process conversation
                print("\nProcessing your request...")
                response = self.agent.process_conversation(user_input)
                print(f"\nAssistant: {response}")

            except KeyboardInterrupt:
                print(f"\nConversation interrupted. Goodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")
                continue


def main():
    """Main function to run the conversation interface"""

    # Check environment variables
    if not os.getenv('OPENAI_API_KEY'):
        print("Warning: OPENAI_API_KEY not found in environment variables")
        return

    print("TOP & TOWN PRODUCT ASSISTANT")
    print("=" * 50)
    user_id = input("Enter your name: ").strip()
    if not user_id:
        user_id = "guest"

    interface = ConversationInterface(user_id)
    interface.start_conversation()


if __name__ == '__main__':
    main()