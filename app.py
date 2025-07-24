# -----------------------------------------------------------------
# Streamlit Emergency Locator and Dispatch Alerter
#
# File: app.py
#
# Instructions:
# 1. Create a file named 'app.py' in your GitHub repository.
# 2. Copy and paste all the code from this document into that file.
# 3. Ensure 'requirements.txt', 'packages.txt', and 'vercel.json' are also in the repository.
# 4. Set up your secret keys as environment variables in your Vercel project settings.
# -----------------------------------------------------------------

import streamlit as st
from streamlit_folium import st_folium
import osmnx as ox
import folium
import openrouteservice
from geopy.distance import geodesic
from folium.plugins import PolyLineTextPath
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
import os # <-- Import the os module

# --- START OF CONFIGURATION ---

# 🔑 Load credentials securely from environment variables
# These will be set in the Vercel project settings.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
VERIFIED_RECIPIENT_NUMBER = os.getenv("VERIFIED_RECIPIENT_NUMBER")
ORS_API_KEY = os.getenv("ORS_API_KEY")

# --- END OF CONFIGURATION ---


# --- BACKEND FUNCTIONS ---

def make_emergency_call():
    """Initiates an automated voice call using Twilio."""
    # Check if Twilio credentials are provided
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, VERIFIED_RECIPIENT_NUMBER]):
        st.warning("📞 Twilio credentials are not fully configured in Vercel environment variables. Skipping call.")
        return

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message_to_say = "emergency situation, please help."
        response = VoiceResponse()
        response.say(message_to_say, voice='alice', language='en-US')
        call = client.calls.create(
            twiml=str(response),
            to=VERIFIED_RECIPIENT_NUMBER,
            from_=TWILIO_PHONE_NUMBER
        )
        st.info(f"📞 Initiating emergency call to {VERIFIED_RECIPIENT_NUMBER}... (Call SID: {call.sid})")
    except Exception as e:
        st.error(f"❌ Twilio Call Exception: {e}")
        st.warning("Please check your Twilio credentials and phone numbers in Vercel settings.")

def get_ors_route_coords(start, end, api_key):
    """Gets route coordinates and details from OpenRouteService."""
    if not api_key:
        st.error("❌ OpenRouteService API key is not configured in Vercel environment variables.")
        return [], None, None
        
    client = openrouteservice.Client(key=api_key)
    try:
        route = client.directions(
            coordinates=[(start[1], start[0]), (end[1], end[0])],
            profile='driving-car',
            format='geojson'
        )
        coords = route['features'][0]['geometry']['coordinates']
        coords_latlon = [(lat, lon) for lon, lat in coords]
        summary = route['features'][0]['properties']['summary']
        return coords_latlon, summary['duration'], summary['distance']
    except Exception as e:
        st.error(f"❌ OpenRouteService Exception: {e}")
        return [], None, None

def find_and_map_route(source_name, emergency_type):
    """Main function to find the nearest service, map the route, and make a call."""
    tag_mapping = {
        "Medical": {"amenity": "hospital"},
        "Fire": {"amenity": "fire_station"},
        "Police": {"amenity": "police"}
    }

    with st.spinner(f"Searching for nearest {emergency_type} service..."):
        try:
            # Step 1: Geocode location
            source_point = ox.geocode(source_name + ", Bangalore, India")
        except Exception as e:
            st.error(f"Could not find location: '{source_name}'. Please try a more specific address or landmark. Error: {e}")
            return

        # Step 2: Find nearby services
        services = ox.features_from_point(source_point, tags=tag_mapping[emergency_type], dist=5000)

        if services.empty:
            st.error(f"❌ No {emergency_type} services found within 5km.")
            return

        # Step 3: Extract coordinates and names
        service_coords, service_names = [], []
        for _, row in services.iterrows():
            geom = row["geometry"]
            name = row.get("name", f"Unnamed {emergency_type}")
            if geom.geom_type == 'Point':
                service_coords.append((geom.y, geom.x))
                service_names.append(name)
            elif geom.geom_type in ['Polygon', 'MultiPolygon']:
                centroid = geom.centroid
                service_coords.append((centroid.y, centroid.x))
                service_names.append(name)

        # Step 4: Find the closest service
        distances = [geodesic(source_point, coord).meters for coord in service_coords]
        min_idx = distances.index(min(distances))
        nearest_coord = service_coords[min_idx]
        nearest_name = service_names[min_idx]

    st.success(f"Found nearest service: {nearest_name}")

    with st.spinner("Calculating best route..."):
        # Step 5: Get route from ORS
        route_coords, duration_sec, distance_m = get_ors_route_coords(source_point, nearest_coord, ORS_API_KEY)

        if not route_coords:
            # Error is already handled in the get_ors_route_coords function
            return

        # Step 6: Create satellite map
        m = folium.Map(
            location=source_point,
            zoom_start=14,
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri World Imagery"
        )

        # Add markers
        folium.Marker(source_point, popup="Your Location", icon=folium.Icon(color='blue', icon='user', prefix='fa')).add_to(m)
        icon_map = {"Medical": "hospital", "Fire": "fire-extinguisher", "Police": "building-shield"}
        folium.Marker(nearest_coord, popup=nearest_name, icon=folium.Icon(color='red', icon=icon_map[emergency_type], prefix='fa')).add_to(m)

        # Draw route
        polyline = folium.PolyLine(route_coords, color="orange", weight=6, opacity=0.9, tooltip=f"Route to {nearest_name}").add_to(m)
        PolyLineTextPath(polyline, '➔ ', repeat=True, offset=7, attributes={'fill': 'white', 'font-weight': 'bold', 'font-size': '18'}).add_to(m)

        # Display map in Streamlit
        st_folium(m, width=725, height=500)

        # Print route info
        distance_km = round(distance_m / 1000, 2)
        duration_min = round(duration_sec / 60, 2)
        
        st.subheader("Route Information")
        st.markdown(f"**✅ Nearest {emergency_type} Service:** `{nearest_name}`")
        st.markdown(f"**📏 Distance:** `{distance_km} km`")
        st.markdown(f"**🚗 Estimated Time:** `{duration_min} minutes`")

        # Step 7: Make the emergency call
        make_emergency_call()


# --- STREAMLIT UI ---

st.set_page_config(page_title="Emergency Route Finder", layout="wide")

st.title("🚨 Emergency Route Finder & Alerter")
st.markdown("This tool finds the nearest emergency service (in Bangalore, India), maps the fastest driving route, and automatically places a call to a designated number.")

# User Inputs
source_name = st.text_input("📍 Enter your current location (e.g., a landmark, address, or area)", "RV College of Engineering")
emergency_type = st.selectbox("🚨 Select the type of emergency", ("Medical", "Fire", "Police"))

# Button to trigger the process
if st.button("Find Route & Alert"):
    if source_name:
        find_and_map_route(source_name, emergency_type)
    else:
        st.warning("Please enter your location.")
