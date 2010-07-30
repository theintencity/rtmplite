/* Copyright (c) 2009, Mamta Singh. See README for details. */
package model
{
	import flash.events.AsyncErrorEvent;
	import flash.events.ErrorEvent;
	import flash.events.EventDispatcher;
	import flash.events.IOErrorEvent;
	import flash.events.NetStatusEvent;
	import flash.events.SecurityErrorEvent;
	import flash.net.NetConnection;
	import flash.net.NetStream;
	import flash.net.ObjectEncoding;
	import flash.net.SharedObject;
	
	/**
	 * The Connector object provides the abstraction and API to connect to the backend SIP-RTMP
	 * gateway. To the rest of the Flash application, this acts as the data model.
	 * 
	 * The object abstracts a single-user, single-line, SIP user agent. In particular, it has one
	 * active SIP registration, and can be in atmost one active SIP call. It also holds the
	 * audio video streams to and from the remote party.
	 */
	public class Connector extends EventDispatcher
	{
		//--------------------------------------
		// CLASS CONSTANTS
		//--------------------------------------
		
		/**
		 * Various states in the connector. The 'idle' state means it is not yet connected to
		 * the gateway service. The connecting state indicates a connection is in progress. The
		 * connected state indicates that it is connected to the gateway server. After this,
		 * the outbound, inbound and active are call-specific states for pending outbound call,
		 * pending inbound call and active call, respectively. The connected state also indicate
		 * idle call status, i.e., you are ready for the call, but there is no call state yet.
		 */
		public static const IDLE:String      = "idle";
		public static const CONNECTING:String = "connecting";
		public static const CONNECTED:String = "connected";
		public static const OUTBOUND:String  = "outbound";
		public static const INBOUND:String   = "inbound";
		public static const ACTIVE:String    = "active";
		
		/**
		 * The connector stores and exposes certain properties to the main application. These
		 * properties are used in the View to display and be editable. These are also stored in
		 * the local shared object if user chose to remember his configuration. 
		 */
		public static const allowedParameters:Array = ["signupURL", "gatewayURL", "sipURL", "authName", "authPass", "displayName", "targetURL", "rate"];
		
		/**
		 * Maximum size of the call history in terms of number of last unique dialed or received
		 * SIP URLs.
		 */
		private static const MAX_HISTORY_SIZE:uint = 20;
		
		//--------------------------------------
		// PRIVATE PROPERTIES
		//--------------------------------------
		
		/**
		 * Internal property to store the connector's state.
		 */
		private var _currentState:String = IDLE;
		
		/**
		 * The local shared object to store the configuration properties.
		 */
		private var so:SharedObject;
		
		/**
		 * The current index in the call history list.
		 */
		private var historyIndex:int = -1;
		
		/**
		 * The unique NetConnection that is used to connect to the gateway service.
		 */
		private var nc:NetConnection;
		
		/**
		 * The two NetStream objects: one for playing remote audio and video, and other
		 * to publish out own audio and video.
		 */
		private var _play:NetStream, _publish:NetStream;
		
		//--------------------------------------
		// PUBLIC PROPERTIES
		//--------------------------------------
		
		[Bindable]
		/**
		 * The signupURL is an http URL pointing to a web site that allows a user to signup
		 * for this service.
		 * Since this implementation doesn't restrict usage, the property is not used currently.
		 */
		public var signupURL:String;
		
		[Bindable]
		/**
		 * The gatewayURL property is an rtmp URL string that points to the sip application on
		 * the SIP-RTMP gateway server. If you are running the server locally, this will typically
		 * be "rtmp://localhost/sip". If you are using the service from a gateway running on
		 * say "somehost.server.net" then the URL will be "rtmp://somehost.server.net".
		 */
		public var gatewayURL:String;

		[Bindable]
		/**
		 * The sipURL property is a SIP address of record of the local user. It does not have
		 * the "sip:" prefix. For example, if you are running a SIP server on host "192.168.1.3"
		 * and if your SIP username is "bob" then sipURL will be "bob@192.168.1.3". If you are
		 * using an existing SIP service such as iptel.org and your username is "alice" then
		 * sipURL will be "alice@iptel.org".
		 */
		public var sipURL:String;
		
		[Bindable]
		/**
		 * The authName property stores your SIP authentication name, which is typically same as
		 * your username portion of the sipURL.
		 */
		public var authName:String;
		
		[Bindable]
		/**
		 * The authPass property stores your SIP authentication password. You should supply this
		 * even if your server doesn't do SIP authentication during registration. Without this
		 * property, the SIP registration process is skipped. On the other hand, if you just
		 * want the client to connect to the gateway service without doing SIP registration, then
		 * do not set this property. Without a SIP registration, you lose the ability to receive
		 * incoming calls, but can still make outbound calls, provided your SIP service allows
		 * outbound calls without registration.
		 */
		public var authPass:String;
		
		[Bindable]
		/**
		 * The displayName property stores your real name such as "Bob Smith" which is used as
		 * your display name during registration and outbound calls.
		 */
		public var displayName:String; 
		
		[Bindable]
		/**
		 * The targetURL property stores a SIP address of the remote party, to which your are
		 * about to make a call, have made a call or have received a call from in the past.
		 * The format of this property is flexible, e.g., 'alice@iptel.org', 'sip:alice@iptel.org'
		 * and '"Alice Smith" <sip:alice@iptel.org>' are all valid. Note that you can also
		 * supply a telephone number, e.g., 'tel:12121234567' as a targetURL provided your
		 * SIP server supports it.
		 */
		public var targetURL:String;
		
		[Bindable]
		/**
		 * The current or last status message for this connector. This is used by the view to
		 * post the status message to the user.
		 */
		public var status:String;
		
		[Bindable]
		/**
		 * Whether the user wants to remember the configuration properties in a local shared object
		 * so that next time the user refreshes the page or visits the page, he doesn't have to
		 * enter the configuration again. If a valid configuration such as gatewayURL, sipURL,
		 * authName and authPass are present, then the client automatically connects and registers
		 * the service on load.
		 */
		public var remember:Boolean = false;
		
		[Bindable]
		/**
		 * The rate of Speex audio captured by microphone is either "narrowband" or "wideband".
		 * Default is "wideband".
		 */
		public var rate:String = "wideband";
		
		//--------------------------------------
		// CONSTRUCTOR
		//--------------------------------------
		
		/**
		 * Constructing a new connector object just loads the configuration from
		 * local shared object if available.
		 */
		public function Connector()
		{
			so = SharedObject.getLocal("phone");
			load();
		}
		
		//--------------------------------------
		// GETTERS/SETTERS
		//--------------------------------------
		
		[Bindable]
		/**
		 * The currentState property represents connector's state as mentioned before.
		 * Changing the state also updates the status property to reflect the user
		 * understandable status message such as "Connecting..."
		 */
		public function get currentState():String
		{
			return _currentState;
		}
		public function set currentState(value:String):void
		{
			var oldValue:String = _currentState;
			_currentState = value;
			
			switch (value) {
				case IDLE:
					if (oldValue == null)
						status = _("Initializing") + "...";
					else
						status = _("Disconnected from service");
					stopPublishPlay();
					break;
				case CONNECTING:
					status = _("Connecting") + "...";
					break;
				case CONNECTED:
					if (oldValue == CONNECTING)
						status = _("Logged in as {0}", sipURL);
					else if (oldValue == OUTBOUND)
						status = _("Call cancelled");
					else
						status = _("Call terminated");
					stopPublishPlay();
					break;
				case OUTBOUND:
					historyAdd(targetURL);
					status = _("Calling out {0}", targetURL) + "...";
					break;
				case INBOUND:
					historyAdd(targetURL);
					status = _("Call from {0}", targetURL) + "...";
					break;
				case ACTIVE:
					status = _("Call connected");
					// publish and play
					startPublishPlay();
					break;
			}
		}
		
		/**
		 * The read-only playStream property gives access to the currently playing
		 * NetStream which plays audio video from the remote party.
		 */
		public function get playStream():NetStream
		{
			return _play;
		}
		
		/**
		 * The read-only publishStream property gives access to the currently published
		 * NetStream which publishes audio video of the local party.
		 */
		public function get publishStream():NetStream
		{
			return _publish;
		}
		
		//--------------------------------------
		// PUBLIC METHODS
		//--------------------------------------
		
		/**
		 * The method initiates a connection to the gateway service. If the first two arguments
		 * are supplied for gatewayURL and sipURL, then it updates its internal state with
		 * all the supplied arguments before initiating the connection. The state change
		 * reflects the connection status. 
		 * 
		 * All the params map to the corresponding properties in this object. If a authPass is
		 * supplied, then the gateway also does SIP registration after a successful connection
		 * with the gateway.
		 */
		public function connect(gatewayURL:String=null, sipURL:String=null, authName:String=null, authPass:String=null, displayName:String=null):void
		{
			if (gatewayURL != null && sipURL != null) {
				this.gatewayURL = gatewayURL;
				this.sipURL = sipURL;
				this.authName = authName;
				this.authPass = authPass;
				this.displayName = displayName;
			}
			trace("login " + this.gatewayURL + "," + this.sipURL + "," + this.authName + "," + this.displayName);

			if (this.gatewayURL != null && this.sipURL != null)
				connectInternal();
		}

		/**
		 * The method causes the connector to disconnect with the gateway service.
		 * In the back-end, the gateway does SIP unregistration, if needed, when the 
		 * client disconnects either explicitly (by calling this method) or implicitly
		 * by unloading the Flash application from the browser.
		 */
		public function disconnect():void
		{
			disconnectInternal();
		}
		
		/**
		 * The method initiates outbound call to the given destination URL. The supplied argument
		 * is first assigned to the targetURL property before initiating the call. It invokes the
		 * "invite" RPC on the connection.
		 */
		public function invite(sipURL:String):void
		{
			targetURL = sipURL;
			inviteInternal();
		}
		
		/**
		 * The method accepts a pending incoming call. It invokes the "accept" RPC on the 
		 * connection.
		 */ 
		public function accept():void
		{
			if (currentState == INBOUND) {
				currentState = ACTIVE;
				if (nc != null) 
					nc.call("accept", null);
			}
		}

		/**
		 * The method rejects a pending inbound call. It invokes the "reject" RPC on the
		 * connection.
		 */
		public function reject(reason:String):void
		{
			if (currentState == INBOUND) {
				currentState = CONNECTED;
				if (nc != null)
					nc.call("reject", null, reason);
			}
		}
		
		/**
		 * The method terminates an active call or cancels an outbound call. It invokes the
		 * "bye" RPC on the connection.
		 */
		public function bye():void
		{
			if (currentState == OUTBOUND || currentState == ACTIVE) { 
				currentState = CONNECTED;
				if (nc != null) {
					nc.call("bye", null);
				}
			}
			//TODO: doIncomingCall();
		}
		
		/**
		 * The callback is invoked by the gateway to indicate an incoming call from the
		 * given "frm" user to this "to" user. The "frm" argument is in the same format as
		 * targetURL, and it gets assigned to targetURL before the state is changed to
		 * reflect incoming call. The application uses targetURL property to know who called.
		 */
		public function invited(frm:String, to:String):void
		{
			trace("invited frm=" + frm);
			this.targetURL = frm;
			if (currentState == CONNECTED)
				currentState = INBOUND;
		}
		
		/**
		 * The callback is invoked by the gateway to indicate that an incoming call is 
		 * cancelled by the remote party. The "frm" and "to" arguments have the same 
		 * meaning as in the "invited" method. The connector changes it's state to no-call
		 * if an incoming call is cancelled.
		 */
		public function cancelled(frm:String, to:String):void
		{
			trace("cancelled frm=" + frm);
			if (currentState == INBOUND && this.targetURL == frm)
				currentState = CONNECTED;
		}
		
		/**
		 * The callback is invoked by the gateway to indicate that an outbound call 
		 * is accepted by the remote party. The connector changes the call state to 'active'.
		 */
		public function accepted():void
		{
			trace("accepted");
			if (currentState == OUTBOUND)
				currentState = ACTIVE;
		}
		
		/**
		 * The callback is invoked by the gateway to indicate that an outbound call
		 * failed for some reason. The connector changes the call state to no-call and
		 * updates the status property to reflec the reason for call rejection.
		 */
		public function rejected(reason:String):void
		{
			trace("rejected reason=" + reason);
			if (currentState == OUTBOUND) {
				currentState = CONNECTED;
				this.status = _("reason") + ": " + reason;
			}
		}
		
		/**
		 * The callback is invoked by the gateway to indicate that an active call is 
		 * terminated by the remote party. The connector changes the call state to no-call.
		 */
		public function byed():void
		{
			trace("byed");
			if (currentState == ACTIVE)
				currentState = CONNECTED;
		}
		
		/**
		 * The method is used to add a given address to the cal history. The call history is
		 * maintained in the shared object, and has a cap of 20 items in the history. This is
		 * invoked when the connector goes in outbound or inbound call state.
		 * 
		 * @param addr the address string to be added to the history.
		 */
		public function historyAdd(addr:String):void
		{
			if (so.data.history != undefined) {
				(so.data.history as Array).push(addr);
				var prev:int = (so.data.history as Array).indexOf(addr);
				if (prev < (so.data.history as Array).length - 1) {
					(so.data.history as Array).splice(prev, 1);
				} 
				if ((so.data.history as Array).length > MAX_HISTORY_SIZE) {
					(so.data.history as Array).splice(0, (so.data.history as Array).length - MAX_HISTORY_SIZE);
				}
				historyIndex = (so.data.history as Array).length - 1;
				
				so.data.targetURL = addr; 
				so.flush();
			}
		}
		
		/**
		 * The method changes the targetURL to reflect the previous history item in
		 * the call history.
		 */
		public function historyPrev():void
		{
			if (so.data.history != undefined) {
				trace("history=" + so.data.history);
				if (historyIndex > 0)
					--historyIndex;
				if (historyIndex >= 0 && historyIndex < (so.data.history as Array).length)
					targetURL = (so.data.history as Array)[historyIndex];
			}
		}
		
		/**
		 * The method changes the targetURL to reflect the next history item in 
		 * the call history.
		 */
		public function historyNext():void
		{
			if (so.data.history != undefined) {
				trace("history=" + so.data.history);
				if (historyIndex < (so.data.history as Array).length - 1)
					++historyIndex;
				if (historyIndex >= 0 && historyIndex < (so.data.history as Array).length)
					targetURL = (so.data.history as Array)[historyIndex];
			}
		}
		
		/**
		 * The method is invoked on startup to load the configuration properties
		 * from the local shared object, if the user had asked to remeber the 
		 * configuration.
		 */
		public function load():void
		{
			var name:String;
			
			remember = (so.data.remember == true);
			
			if (remember) {
				if (so.data.history == undefined)
					so.data.history = [];
				if (historyIndex < 0 && (so.data.history as Array).length > 0)
					historyIndex = (so.data.history as Array).length - 1;
					 
				for each (name in allowedParameters) {
					this[name] = so.data[name];
				}
			}
		}
		
		/**
		 * The method saves the local properties into the local shared object if the
		 * user has asked to remember the configuration, otherwise it clears the
		 * local shared object.
		 */
		public function save():void
		{
			var name:String;
			
			if (remember) {
				so.data.remember = true;
				for each (name in allowedParameters) {
					so.data[name] = this[name];
				}
			}
			else {
				delete so.data.remember;
				delete so.data.history;
				for each (name in allowedParameters) {
					delete so.data[name];
				}
			}
			so.flush();
		}
		
		/**
		 * This is a convinience method to determine whether the given string 'str'
		 * contains all digits or not? The digits include 0-9 as well as '*' and '#'
		 * keys found on telephone dial-pad.
		 */
		public function isDigit(str:String):Boolean
		{
			var result:Boolean = str.length > 0;
			for (var i:int=0; i<str.length; ++i) {
				var c:int = str.charCodeAt(i);
				if (!(c >= 48 && c <= 57 || c == 35 || c == 42)) {
					result = false;
					break;
				}
			}
			return result;
		}
		
		/**
		 * The method sends a DTMF digit to the remote party in an active call.
		 * It invokes the "sendDTMF" RPC on the connection.
		 * TODO: implement this method.
		 */
		public function sendDigit(str:String):void
		{
			trace("sending digit " + str);
		}
		
		//--------------------------------------
		// PRIVATE METHODS
		//--------------------------------------
		
		/**
		 * Internal method to actually do connection to the gateway service.
		 */
		private function connectInternal():void
		{
			if (currentState == IDLE) {
				currentState = CONNECTING;
				
				if (nc != null) {
					nc.close();
					nc = null; _play = _publish = null;
				}
				
		    	nc = new NetConnection();
		    	nc.objectEncoding = ObjectEncoding.AMF0; // This is MUST!
		    	nc.client = this;
		    	nc.addEventListener(NetStatusEvent.NET_STATUS, netStatusHandler, false, 0, true);
		    	nc.addEventListener(IOErrorEvent.IO_ERROR, errorHandler, false, 0, true);
		    	nc.addEventListener(SecurityErrorEvent.SECURITY_ERROR, errorHandler, false, 0, true);
		    	nc.addEventListener(AsyncErrorEvent.ASYNC_ERROR, errorHandler, false, 0, true);
		    	
		    	var url:String = this.gatewayURL + "/" + (this.sipURL.substr(0, 4) == "sip:" ? this.sipURL.substr(4) : this.sipURL); 
		    	trace('connect() ' + url);
			    nc.connect(url, this.authName, this.authPass, this.displayName, this.rate);
			}
		}
		
		/**
		 * When the connection status is received take appropriate actions.
		 * For example, when the connection is successful, create the play and publish 
		 * streams. The method also updates the local state.
		 */
		private function netStatusHandler(event:NetStatusEvent):void 
		{
			trace('netStatusHandler() ' + event.type + ' ' + event.info.code);
			switch (event.info.code) {
			case 'NetConnection.Connect.Success':
				_publish = new NetStream(nc);
				_play = new NetStream(nc);
				_publish.addEventListener(NetStatusEvent.NET_STATUS, netStatusHandler, false, 0, true);
				_play.addEventListener(NetStatusEvent.NET_STATUS, netStatusHandler, false, 0, true);
				if (currentState == CONNECTING)
					currentState = CONNECTED;
				break;
			case 'NetConnection.Connect.Failed':
			case 'NetConnection.Connect.Rejected':
			case 'NetConnection.Connect.Closed':
				if (nc != null)
					nc.close();
				nc = null; _play = _publish = null;
		    	currentState = IDLE;
				if ('description' in event.info)
		    		this.status = _("reason") + ": " + event.info.description;
				break;
			}
		}
		
		/**
		 * When there is an error in the connection, close the connection and
		 * any associated stream.
		 */
		private function errorHandler(event:ErrorEvent):void 
		{
			trace('errorHandler() ' + event.type + ' ' + event.text);
			if (nc != null)
				nc.close();
			nc = null; _play = _publish = null;
			currentState = IDLE;
			this.status = _("reason") + ": " + event.type + " " + event.text;
		}
		
		/**
		 * Internal method to disconnect with the gateway service and to
		 * close the connection.
		 */
		private function disconnectInternal():void
		{
			currentState = IDLE;
        	if (nc != null) {
        		nc.close();
				nc = null; _play = _publish = null;
        	}
		}
		
		/**
		 * Internal method to invoke the outbound call invitation RPC.
		 */
		private function inviteInternal():void
		{
			if (currentState == CONNECTED) {
				
				if (nc != null) {
					currentState = OUTBOUND;
					nc.call("invite", null, this.targetURL);
				}
				else {
					this.status = _("Must be connected to invite");
				}
			}
		}
		
		/**
		 * When the call is active, publish local stream and play remote stream.
		 */
		private function startPublishPlay():void
		{
			trace('startPublishPlay');
			if (_publish != null)
				_publish.publish("local");
			if (_play != null)
				_play.play("remote");
		}
		
		/**
		 * When the call is terminated close both local and remote streams.
		 */
		private function stopPublishPlay():void
		{
			trace('stopPublishPlay');
			if (_publish != null)
				_publish.close();
			if (_play != null)
				_play.close();
		}
	}
}
