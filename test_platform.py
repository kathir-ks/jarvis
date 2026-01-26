"""Test script to demonstrate Jarvis platform capabilities."""
import requests
import json
import time
from typing import Dict, Any

BASE_URL = "http://localhost:8000"

def print_response(title: str, response: requests.Response):
    """Pretty print API response."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        print(json.dumps(data, indent=2))
    except:
        print(response.text)
    print()

def test_health():
    """Test health endpoint."""
    response = requests.get(f"{BASE_URL}/health")
    print_response("Health Check", response)
    return response.status_code == 200

def create_agent() -> str:
    """Create a master agent."""
    payload = {
        "agent_type": "MASTER",
        "config": {
            "llm_provider": "openai",
            "model": "gpt-4",
            "temperature": 0.7,
            "loop_interval_seconds": 1,
            "checkpoint_interval_seconds": 30
        },
        "tools_enabled": ["web_search", "browser"]
    }
    
    response = requests.post(f"{BASE_URL}/agents", json=payload)
    print_response("Create Master Agent", response)
    
    if response.status_code == 201:
        return response.json()["agent_id"]
    return None

def get_agent(agent_id: str):
    """Get agent details."""
    response = requests.get(f"{BASE_URL}/agents/{agent_id}")
    print_response(f"Get Agent: {agent_id}", response)
    return response.json() if response.status_code == 200 else None

def start_agent(agent_id: str):
    """Start agent runtime."""
    response = requests.post(f"{BASE_URL}/agents/{agent_id}/start")
    print_response(f"Start Agent: {agent_id}", response)
    return response.status_code == 204

def submit_task(agent_id: str, task_type: str, description: str, params: Dict[str, Any]) -> str:
    """Submit a task to an agent."""
    payload = {
        "task_type": task_type,
        "task_description": description,
        "task_params": params,
        "priority": 8
    }
    
    response = requests.post(f"{BASE_URL}/tasks?agent_id={agent_id}", json=payload)
    print_response(f"Submit {task_type} Task", response)
    
    if response.status_code == 201:
        return response.json()["task_id"]
    return None

def get_task_status(task_id: str):
    """Get task status."""
    response = requests.get(f"{BASE_URL}/tasks/{task_id}")
    print_response(f"Task Status: {task_id}", response)
    return response.json() if response.status_code == 200 else None

def spawn_sub_agent(parent_agent_id: str) -> str:
    """Spawn a sub-agent."""
    payload = {
        "config": {
            "model": "gpt-3.5-turbo",
            "temperature": 0.5
        },
        "tools_enabled": ["web_scraper"]
    }
    
    response = requests.post(f"{BASE_URL}/agents/{parent_agent_id}/spawn", json=payload)
    print_response(f"Spawn Sub-Agent from {parent_agent_id}", response)
    
    if response.status_code == 201:
        return response.json()["agent_id"]
    return None

def checkpoint_agent(agent_id: str):
    """Force checkpoint agent state."""
    response = requests.post(f"{BASE_URL}/agents/{agent_id}/checkpoint")
    print_response(f"Checkpoint Agent: {agent_id}", response)
    return response.status_code == 204

def stop_agent(agent_id: str):
    """Stop agent runtime."""
    response = requests.post(f"{BASE_URL}/agents/{agent_id}/stop")
    print_response(f"Stop Agent: {agent_id}", response)
    return response.status_code == 204

def main():
    """Run comprehensive platform test."""
    print("\n" + "="*60)
    print("  JARVIS PLATFORM TEST SUITE")
    print("="*60)
    
    # 1. Health check
    print("\n[1/8] Testing health endpoint...")
    if not test_health():
        print("[FAIL] Health check failed!")
        return
    print("[PASS] Health check passed!")
    
    # 2. Create master agent
    print("\n[2/8] Creating master agent...")
    agent_id = create_agent()
    if not agent_id:
        print("[FAIL] Failed to create agent!")
        return
    print(f"[PASS] Master agent created: {agent_id}")
    
    # 3. Get agent details
    print("\n[3/8] Fetching agent details...")
    agent = get_agent(agent_id)
    if not agent:
        print("[FAIL] Failed to get agent!")
        return
    print(f"[PASS] Agent status: {agent['status']}")
    
    # 4. Start agent runtime
    print("\n[4/8] Starting agent runtime...")
    if not start_agent(agent_id):
        print("[FAIL] Failed to start agent!")
        return
    print("[PASS] Agent runtime started!")
    
    # Wait a moment for agent to initialize
    time.sleep(2)
    
    # 5. Submit a research task
    print("\n[5/8] Submitting research task...")
    task_id = submit_task(
        agent_id,
        "RESEARCH",
        "Research AI trends in 2026",
        {"query": "AI trends 2026", "max_results": 5}
    )
    if not task_id:
        print("[FAIL] Failed to submit task!")
        return
    print(f"[PASS] Task submitted: {task_id}")
    
    # 6. Check task status
    print("\n[6/8] Checking task status...")
    time.sleep(2)
    task = get_task_status(task_id)
    if task:
        print(f"[PASS] Task status: {task['status']}")
    
    # 7. Spawn sub-agent
    print("\n[7/8] Spawning sub-agent...")
    sub_agent_id = spawn_sub_agent(agent_id)
    if sub_agent_id:
        print(f"[PASS] Sub-agent created: {sub_agent_id}")
        
        # Get sub-agent details
        sub_agent = get_agent(sub_agent_id)
        if sub_agent:
            print(f"   Parent agent: {sub_agent['parent_agent_id']}")
    
    # 8. Checkpoint and stop
    print("\n[8/8] Checkpointing and stopping agent...")
    checkpoint_agent(agent_id)
    stop_agent(agent_id)
    print("[PASS] Agent stopped!")
    
    # Final summary
    print("\n" + "="*60)
    print("  TEST SUMMARY")
    print("="*60)
    print(f"[SUCCESS] Master Agent ID: {agent_id}")
    if sub_agent_id:
        print(f"[SUCCESS] Sub-Agent ID: {sub_agent_id}")
    print(f"[SUCCESS] Task ID: {task_id}")
    print("\n*** All tests completed successfully! ***")
    print("\nYou can now:")
    print(f"  - View agent: GET {BASE_URL}/agents/{agent_id}")
    print(f"  - View task: GET {BASE_URL}/tasks/{task_id}")
    print(f"  - Start agent again: POST {BASE_URL}/agents/{agent_id}/start")
    print("="*60 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[WARN] Test interrupted by user")
    except Exception as e:
        print(f"\n\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
