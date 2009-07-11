/* Copyright (c) 2009, Mamta Singh. See README for details. */
package {
	import mx.resources.ResourceManager;
	import mx.resources.Locale;
	
	/**
	 * The resource bundle to embed.
	 */
	[ResourceBundle("main")]
	
	/**
	 * The function _ is used to localise the strings. See examples in rest of the code on
	 * how this is used. This works in conjunction with the appropriate locale file.
	 */
	public function _(format:String, ...args):String 
	{
		var result:String = ResourceManager.getInstance().getString("main", format.split(" ").join("_"), args);
		if (result == null) {
			result = format;
			for (var i:int=0; i<args.length; ++i) 
				result = result.replace("{" + i.toString() + "}", args[i].toString());
		}
		return result;
	}
}
